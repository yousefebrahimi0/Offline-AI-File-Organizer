"""Watch-folder processing with stable-file detection and bounded parallel analysis."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class WatchFolderService:
    """Debounce file events, analyse files concurrently, and serialize file moves."""

    def __init__(
        self,
        organizer,
        rename: bool = True,
        organize: bool = True,
        workers: int = 2,
        stability_seconds: float = 1.5,
        poll_interval: float = 0.25,
        stability_timeout: float = 300.0,
        auto_apply: bool = False,
    ):
        if not rename and not organize:
            raise ValueError("Watch mode requires --rename, --organize, or both.")
        if workers < 1:
            raise ValueError("workers must be at least 1.")
        if stability_seconds < 0 or poll_interval <= 0 or stability_timeout <= 0:
            raise ValueError("Stability delay must be non-negative; poll interval and timeout must be positive.")

        self.organizer = organizer
        self.root = organizer.root_folder.resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"Watch folder does not exist: {self.root}")

        self.rename = rename
        self.organize = organize
        self.workers = workers
        self.stability_seconds = stability_seconds
        self.poll_interval = poll_interval
        self.stability_timeout = stability_timeout
        self.auto_apply = auto_apply

        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="file-organizer")
        self._state_lock = threading.RLock()
        self._apply_lock = threading.Lock()
        self._plan_write_lock = threading.Lock()
        self._pending = set()
        self._dirty = set()
        self._last_seen = {}
        self._last_processed = {}
        self._reserved_targets = set()
        self._self_moved_paths = set()
        self._plan_actions: Dict[str, Dict[str, Any]] = {}
        self._log_actions = []
        self._closing = False
        self._futures = set()
        self._stats = {"events": 0, "analysed": 0, "planned": 0, "moved": 0, "skipped": 0, "errors": 0}

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.plan_path = self.root / f"watch_plan_{self.session_id}.json"
        self.log_path = self.root / f"organization_log_watch_{self.session_id}.json"

    @staticmethod
    def _stamp(path: Path) -> Optional[Tuple[int, int]]:
        try:
            if path.is_symlink() or not path.is_file():
                return None
            stat = path.stat()
            return stat.st_size, stat.st_mtime_ns
        except OSError:
            return None

    def _is_candidate(self, path: Path) -> bool:
        if path.is_symlink() or not path.is_file():
            return False
        if path.name.startswith("."):
            return False
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(self.root)
        except (OSError, ValueError):
            return False
        with self._state_lock:
            if os.path.normcase(str(resolved)) in self._self_moved_paths:
                return False
        if path.suffix.lower() not in self.organizer._active_extensions():
            return False
        return not self.organizer._is_ignored(path)

    def submit(self, file_path: str | Path) -> bool:
        """Schedule a file event; repeated identical events are coalesced."""
        path = Path(file_path)
        if not path.is_absolute():
            path = self.root / path
        path = Path(os.path.abspath(path))
        if not self._is_candidate(path):
            return False

        stamp = self._stamp(path)
        if stamp is None:
            return False
        key = os.path.normcase(str(path))

        with self._state_lock:
            if self._closing:
                return False
            self._stats["events"] += 1
            if self._last_processed.get(key) == stamp:
                return False

            if key in self._pending:
                previous = self._last_seen.get(key)
                if previous != stamp:
                    self._dirty.add(key)
                    self._last_seen[key] = stamp
                return False

            self._pending.add(key)
            self._last_seen[key] = stamp
            future = self._executor.submit(self._worker, path, key)
            self._futures.add(future)
            future.add_done_callback(self._discard_future)
            return True

    def _discard_future(self, future) -> None:
        with self._state_lock:
            self._futures.discard(future)

    def _wait_until_stable(self, path: Path) -> Optional[Tuple[int, int]]:
        """Require size and modification time to remain unchanged for the stability window."""
        deadline = time.monotonic() + self.stability_timeout
        last_stamp = None
        unchanged_since = None
        while time.monotonic() <= deadline:
            current = self._stamp(path)
            if current is None:
                return None
            if current != last_stamp:
                last_stamp = current
                unchanged_since = time.monotonic()
            elif unchanged_since is not None and time.monotonic() - unchanged_since >= self.stability_seconds:
                return current
            time.sleep(self.poll_interval)
        print(f"  ⚠️  Timed out waiting for file copy to finish: {path.name}")
        return None

    def _choose_target(self, desired: Path, source: Path) -> Path:
        """Resolve naming collisions under the caller's state/apply lock."""
        target = desired
        counter = 1
        while (
            (target.exists() and target.resolve(strict=False) != source.resolve())
            or os.path.normcase(str(target.resolve(strict=False))) in self._reserved_targets
        ):
            target = desired.with_name(f"{desired.stem} [{counter}]{desired.suffix}")
            counter += 1
        return target

    def _build_action(self, path: Path) -> Optional[Dict[str, Any]]:
        """Analyse one stable source and return a version 3 plan action."""
        before = self.organizer._file_fingerprint(path)
        name, category = self.organizer.analyze_file(path, rename=self.rename, organize=self.organize)
        with self._state_lock:
            self._stats["analysed"] += 1

        if (self.rename and not name) or (self.organize and not category):
            with self._state_lock:
                self._stats["skipped"] += 1
            print(f"  ⚠️  Skipped {path.name}: AI analysis failed or returned incomplete JSON")
            return None

        after = self.organizer._file_fingerprint(path)
        if not self.organizer._fingerprint_matches(after, before):
            with self._state_lock:
                self._stats["skipped"] += 1
            print(f"  ⚠️  Skipped {path.name}: file changed during analysis")
            return None

        file_date = self.organizer.get_file_date_string(path)
        target_dir = self.root / self.organizer.organize_folder_name / category if self.organize else path.parent
        if self.rename:
            base_name = self.organizer.sanitize_filename(f"{name} ({file_date})", max_len=180)
            if not base_name:
                with self._state_lock:
                    self._stats["skipped"] += 1
                return None
            target_name = f"{base_name}{path.suffix}"
        else:
            target_name = path.name

        desired = (target_dir / target_name).resolve(strict=False)
        if desired == path.resolve():
            with self._state_lock:
                self._stats["skipped"] += 1
            return None
        if not self.organizer._path_is_within(desired, self.root):
            raise ValueError(f"Generated destination escapes the watch folder: {desired}")

        return {
            "old_path": str(path.resolve()),
            "new_path": str(desired),
            "category": category if self.organize else "",
            "source_fingerprint": before,
        }

    @staticmethod
    def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
        """Atomically replace a JSON file in the same directory."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(path.parent),
                prefix=".organizer-", suffix=".tmp", delete=False
            ) as stream:
                temp_name = stream.name
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def _persist_plan(self) -> None:
        with self._plan_write_lock:
            with self._state_lock:
                actions = list(self._plan_actions.values())
            if actions:
                self._atomic_write_json(
                    self.plan_path,
                {
                    "version": 3,
                    "root_folder": str(self.root),
                    "timestamp": datetime.now().isoformat(),
                    "actions": actions,
                    },
                )

    def _persist_log(self) -> None:
        # Called while _apply_lock is held, or after all workers have stopped.
        actions = list(self._log_actions)
        if actions:
            self._atomic_write_json(
                self.log_path,
                {
                    "version": 3,
                    "root_folder": str(self.root),
                    "timestamp": datetime.now().isoformat(),
                    "actions": actions,
                },
            )

    def _record_suggestion(self, action: Dict[str, Any]) -> None:
        key = os.path.normcase(action["old_path"])
        with self._state_lock:
            previous = self._plan_actions.get(key)
            if previous:
                previous_target = os.path.normcase(str(Path(previous["new_path"]).resolve(strict=False)))
                self._reserved_targets.discard(previous_target)
            desired = Path(action["new_path"])
            target = self._choose_target(desired, Path(action["old_path"]))
            action = dict(action)
            action["new_path"] = str(target)
            self._reserved_targets.add(os.path.normcase(str(target.resolve(strict=False))))
            self._plan_actions[key] = action
            self._stats["planned"] = len(self._plan_actions)
        self._persist_plan()
        print(f"  → Review proposal: {Path(action['old_path']).name}  ==>  {target.relative_to(self.root)}")

    def _apply_action(self, action: Dict[str, Any]) -> None:
        """Serialize file moves and append a version 3 undo log."""
        with self._apply_lock:
            source = Path(action["old_path"])
            target = self._choose_target(Path(action["new_path"]), source)
            if target == source or not self.organizer._path_is_within(target, self.root):
                raise ValueError(f"Unsafe watch destination: {target}")

            target_key = os.path.normcase(str(target.resolve()))
            with self._state_lock:
                self._self_moved_paths.add(target_key)
            try:
                moved_fingerprint = self.organizer._move_no_overwrite(
                    source, target, expected_fingerprint=action["source_fingerprint"]
                )
            except Exception:
                with self._state_lock:
                    self._self_moved_paths.discard(target_key)
                raise

            logged = dict(action)
            logged["new_path"] = str(target)
            logged["result_fingerprint"] = moved_fingerprint
            self._log_actions.append(logged)
            self._stats["moved"] += 1
            with self._state_lock:
                # Ignore this exact self-generated event version, but allow later edits.
                self._last_processed[target_key] = (
                    moved_fingerprint["size"], moved_fingerprint["mtime_ns"]
                )
                self._self_moved_paths.discard(target_key)
            self._persist_log()
            print(f"  ✓ Automatically organized: {source.name}  ==>  {target.relative_to(self.root)}")

    def _worker(self, path: Path, key: str) -> None:
        """Process one file version at a time; repeat only if the file changes mid-run."""
        try:
            while True:
                stable_stamp = self._wait_until_stable(path)
                if stable_stamp is None:
                    with self._state_lock:
                        self._stats["skipped"] += 1
                    break

                try:
                    action = self._build_action(path)
                    if action:
                        if self.auto_apply:
                            self._apply_action(action)
                        else:
                            self._record_suggestion(action)
                except Exception as exc:
                    with self._state_lock:
                        self._stats["errors"] += 1
                    print(f"  ✗ Watch processing failed for {path.name}: {exc}")

                current_stamp = self._stamp(path)
                with self._state_lock:
                    self._last_processed[key] = stable_stamp
                    self._dirty.discard(key)
                    if current_stamp is not None and current_stamp != stable_stamp:
                        self._last_seen[key] = current_stamp
                        continue
                    self._pending.discard(key)
                    self._last_seen.pop(key, None)
                    return
        finally:
            with self._state_lock:
                self._pending.discard(key)
                self._dirty.discard(key)

    def shutdown(self, wait: bool = True) -> Dict[str, Any]:
        """Stop accepting events, wait for workers, and flush plan/log files."""
        with self._state_lock:
            self._closing = True
        self._executor.shutdown(wait=wait)
        self._persist_plan()
        self._persist_log()
        with self._state_lock:
            stats = dict(self._stats)
        return {
            "stats": stats,
            "plan_path": self.plan_path if self.plan_path.exists() else None,
            "log_path": self.log_path if self.log_path.exists() else None,
        }


def run_watch_mode(
    organizer,
    rename: bool = True,
    organize: bool = True,
    workers: int = 2,
    stability_seconds: float = 1.5,
    auto_apply: bool = False,
) -> Dict[str, Any]:
    """Start watchdog observer until Ctrl+C, then cleanly stop and flush outputs."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError as exc:
        raise RuntimeError("Watch-folder mode requires watchdog. Install it with: pip install watchdog") from exc

    service = WatchFolderService(
        organizer=organizer, rename=rename, organize=organize,
        workers=workers, stability_seconds=stability_seconds, auto_apply=auto_apply
    )

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory:
                service.submit(event.src_path)

        def on_modified(self, event):
            if not event.is_directory:
                service.submit(event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                service.submit(event.dest_path)

        def on_closed(self, event):
            if not event.is_directory:
                service.submit(event.src_path)

    observer = Observer()
    observer.schedule(Handler(), str(organizer.root_folder), recursive=True)
    observer.start()

    mode = "AUTOMATIC APPLY" if auto_apply else "REVIEW-ONLY"
    print(f"\n👀 Watching: {organizer.root_folder}")
    print(f"Mode: {mode} | Workers: {workers} | File stability delay: {stability_seconds:g}s")
    if not auto_apply:
        print("Files will not be moved. A saved review plan will be available when you stop with Ctrl+C.")
    else:
        print(f"Moves will be logged for undo. Log: {service.log_path}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping watcher...")
    finally:
        observer.stop()
        observer.join()
        result = service.shutdown(wait=True)

    print(f"\nWatch session summary: {result['stats']}")
    if result["plan_path"]:
        print(f"✓ Review plan saved: {result['plan_path']}")
        print(f"  Apply it later with: python file_organizer.py --apply-plan \"{result['plan_path']}\"")
    if result["log_path"]:
        print(f"✓ Undo log saved: {result['log_path']}")
    return result
