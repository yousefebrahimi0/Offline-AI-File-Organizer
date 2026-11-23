"""Smart taxonomy, deterministic rules, duplicate detection, and a safe review queue.

No third-party AI dependency. These helpers never move or delete user files.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SMART_SUBCATEGORIES = {
    "Work": ["Projects", "Reports", "Contracts"],
    "Finance": ["Invoices", "Receipts", "Statements", "Taxes"],
    "Personal": ["Identity", "Legal", "Medical"],
    "Education": ["Courses", "Research"],
    "Photos": ["Travel", "People", "Receipts"],
    "Projects": ["Plans", "Designs"],
    "Medical": ["Records", "Prescriptions"],
    "Legal": ["Contracts", "Agreements"],
    "Archive": ["Documents"],
}
PROFILES = ("simple", "smart", "custom")
RESERVED = {".", ".."}


def safe_segment(text: str) -> bool:
    """Reject filesystem separators, drive syntax, and hidden traversal segments."""
    return (
        isinstance(text, str)
        and 0 < len(text) <= 60
        and text not in RESERVED
        and text.strip(" .") == text
        and not any(c in text for c in '<>:"/\\|?*\r\n\t')
        and not (os.name == "nt" and text.upper().split(".")[0] in {
            "CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
            *[f"LPT{i}" for i in range(1, 10)],
        })
    )


class Taxonomy:
    def __init__(self, categories, profile="smart", subcategories=None):
        if profile not in PROFILES:
            raise ValueError("Organization profile must be simple, smart, or custom.")
        self.profile = profile
        self.categories = list(categories)
        if len(set(self.categories)) != len(self.categories) or any(
            not safe_segment(c) for c in self.categories
        ):
            raise ValueError("Category names must be unique, safe folder segments.")
        source = subcategories if subcategories is not None else SMART_SUBCATEGORIES
        if not isinstance(source, dict):
            raise ValueError("Subcategories must be a mapping.")
        self.subcategories = {
            c: list(source.get(c, [])) if profile != "simple" else []
            for c in self.categories
        }
        for root, subs in self.subcategories.items():
            if (
                len(set(subs)) != len(subs)
                or len(subs) > 30
                or any(not safe_segment(s) for s in subs)
            ):
                raise ValueError(f"Unsafe or duplicate subcategories under {root}")

    def category(self, raw: str) -> Optional[str]:
        return next(
            (c for c in self.categories if c.casefold() == str(raw).strip().casefold()),
            None,
        )

    def subcategory(self, category: str, raw: str) -> Optional[str]:
        if not raw:
            return ""
        if self.profile == "simple":
            return ""
        return next(
            (
                item for item in self.subcategories.get(category, [])
                if item.casefold() == str(raw).strip().casefold()
            ),
            None,
        )

    def target_dir(self, root: Path, organize_folder: str, category: str, subcategory: str = "") -> Path:
        valid_category = self.category(category)
        if valid_category is None:
            raise ValueError(f"Unknown category: {category!r}")
        valid_sub = self.subcategory(valid_category, subcategory)
        if valid_sub is None:
            raise ValueError(f"Unknown subcategory for {valid_category}: {subcategory!r}")
        return root / organize_folder / valid_category / valid_sub if valid_sub else root / organize_folder / valid_category

    def prompt_categories(self) -> str:
        if self.profile == "simple":
            return ", ".join(self.categories)
        return "; ".join(
            f"{cat}: {', '.join(self.subcategories[cat]) or 'none'}"
            for cat in self.categories
        )


def atomic_json(path: Path, payload: Any) -> None:
    """Use an exclusive temporary file followed by same-directory replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError("Organizer metadata directory cannot be a symbolic link.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent),
            prefix=".organizer-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class Workspace:
    """An internal metadata directory, never scanned or organized."""
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.folder = self.root / ".organizer"
        if not self.folder.resolve(strict=False).is_relative_to(self.root):
            raise ValueError("Workspace metadata directory escapes the selected folder.")
        self.lock = threading.RLock()

    def read(self, name: str, default):
        if name not in {"rules.json", "review_queue.json", "analysis_cache.json"}:
            raise ValueError("Unknown workspace file.")
        path = self.folder / name
        if not path.exists():
            return default
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Workspace files must not be symbolic links.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return default
        return data if isinstance(data, type(default)) else default

    def write(self, name: str, data) -> None:
        if name not in {"rules.json", "review_queue.json", "analysis_cache.json"}:
            raise ValueError("Unknown workspace file.")
        atomic_json(self.folder / name, data)


class RuleBook:
    """Only explicit, predictable filename/extension/content rules; no AI call."""
    def __init__(self, workspace: Workspace, taxonomy: Taxonomy, configured=None):
        self.workspace, self.taxonomy = workspace, taxonomy
        self.configured = list(configured or [])

    def list_rules(self) -> List[dict]:
        with self.workspace.lock:
            return self.configured + self.workspace.read("rules.json", [])

    def validate(self, rule: dict) -> dict:
        if not isinstance(rule, dict):
            raise ValueError("Rule must be an object.")
        pattern = rule.get("pattern")
        if not isinstance(pattern, str) or not pattern or len(pattern) > 100 or "/" in pattern or "\\" in pattern:
            raise ValueError("Rule must include a simple filename glob, such as *invoice*.pdf")
        category = self.taxonomy.category(rule.get("category"))
        if category is None:
            raise ValueError("Rule category is not in the current taxonomy.")
        sub = self.taxonomy.subcategory(category, rule.get("subcategory", ""))
        if sub is None:
            raise ValueError("Rule subcategory is not allowed in the current taxonomy.")
        contains = rule.get("contains", "")
        if not isinstance(contains, str) or len(contains) > 100:
            raise ValueError("Optional rule text must be 100 characters or fewer.")
        return {"pattern": pattern, "category": category, "subcategory": sub, "contains": contains}

    def add(self, rule: dict) -> dict:
        rule = self.validate(rule)
        with self.workspace.lock:
            rules = self.workspace.read("rules.json", [])
            if rule not in rules:
                rules.append(rule)
                self.workspace.write("rules.json", rules)
        return rule

    def match(self, file_path: Path, preview: Optional[str] = None) -> Optional[dict]:
        for raw in self.list_rules():
            try:
                rule = self.validate(raw)
            except ValueError:
                continue
            if not fnmatch.fnmatch(file_path.name.casefold(), rule["pattern"].casefold()):
                continue
            if rule["contains"]:
                if preview is None or rule["contains"].casefold() not in preview.casefold():
                    continue
            return rule
        return None


class ReviewQueue:
    """Stores only paths/reasons/fingerprints, never extracted contents or API keys."""
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def items(self) -> List[dict]:
        with self.workspace.lock:
            return self.workspace.read("review_queue.json", [])

    def add(self, file_path: Path, reason: str, fingerprint=None) -> None:
        key = str(file_path.resolve(strict=False))
        with self.workspace.lock:
            items = [item for item in self.items() if item.get("path") != key]
            items.append({
                "path": key,
                "reason": str(reason)[:180],
                "sha256": (fingerprint or {}).get("sha256", ""),
                "added_at": datetime.now().isoformat(),
            })
            self.workspace.write("review_queue.json", items[-500:])

    def dismiss(self, file_path: str) -> None:
        with self.workspace.lock:
            remaining = [item for item in self.items() if item.get("path") != file_path]
            self.workspace.write("review_queue.json", remaining)


class DuplicateIndex:
    """A lightweight SHA-256 index, populated as files are considered."""
    def __init__(self):
        self._files: Dict[str, str] = {}
        self.lock = threading.RLock()

    def find_or_register(self, path: Path, fingerprint: dict) -> Optional[str]:
        digest = fingerprint.get("sha256")
        file_key = str(path.resolve(strict=False))
        with self.lock:
            match = self._files.get(digest)
            if match is not None and match != file_key and Path(match).exists():
                return match
            self._files[digest] = file_key
            return None

    def scan_organized(self, organized_root: Path, fingerprint, allowed_extensions) -> None:
        """Index previously organized files once so they can be skipped before AI calls."""
        if not organized_root.is_dir():
            return
        for path in organized_root.rglob("*"):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in allowed_extensions:
                continue
            try:
                self.find_or_register(path, fingerprint(path))
            except (OSError, ValueError):
                continue



class AnalysisCache:
    """Bounded local cache keyed by file content, naming context and model settings."""

    def __init__(self, workspace: Workspace, limit: int = 500):
        self.workspace = workspace
        self.limit = max(20, min(5000, int(limit)))

    @staticmethod
    def key(parts: list) -> str:
        raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[dict]:
        with self.workspace.lock:
            record = self.workspace.read("analysis_cache.json", {}).get(key)
            return dict(record) if isinstance(record, dict) else None

    def put(self, key: str, value: dict) -> None:
        with self.workspace.lock:
            current = self.workspace.read("analysis_cache.json", {})
            current.pop(key, None)
            current[key] = value
            if len(current) > self.limit:
                current = dict(list(current.items())[-self.limit:])
            self.workspace.write("analysis_cache.json", current)
