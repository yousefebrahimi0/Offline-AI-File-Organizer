"""Strict, framework-independent review edits and preflight."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


def review_rows(actions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "Apply": True, "Original": Path(a["old_path"]).name,
            "New filename": Path(a["new_path"]).name,
            "Category": a.get("category", ""),
            "Subcategory": a.get("subcategory", ""),
            "Why": a.get("reason", ""),
            "Source": a.get("source", "ai"),
        }
        for a in actions
    ]


def select_reviewed_actions(
    organizer, original: List[Dict[str, Any]], edited: Iterable[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Edited destinations must obey the approved taxonomy and depth limit."""
    rows = list(edited)
    if len(rows) != len(original):
        raise ValueError("The review table differs in length from the original plan.")
    selected, seen = [], set()
    for action, row in zip(original, rows):
        if not bool(row.get("Apply", False)):
            continue
        old = Path(action["old_path"])
        proposed = Path(action["new_path"])
        filename = row.get("New filename")
        category = row.get("Category", "")
        sub = row.get("Subcategory", action.get("subcategory", ""))

        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Reviewed filenames must be non-empty.")
        if filename != Path(filename).name or filename in {".", ".."}:
            raise ValueError("Filenames cannot contain directory paths.")
        if "/" in filename or "\\" in filename:
            raise ValueError("Filenames cannot contain path separators.")
        if filename != organizer.sanitize_filename(filename, max_len=255):
            raise ValueError(f"Unsafe or invalid filename: {filename}")
        if not filename.lower().endswith(old.suffix.lower()):
            raise ValueError("Reviewed filenames must retain their original extension.")

        if action.get("category"):
            target_dir = organizer.taxonomy.target_dir(
                organizer.root_folder, organizer.organize_folder_name, category, sub
            )
        else:
            if category or sub:
                raise ValueError("Categories cannot be added to a rename-only plan.")
            target_dir = proposed.parent

        target = target_dir / filename
        key = os.path.normcase(str(target.resolve(strict=False)))
        if key in seen:
            raise ValueError(f"Two reviewed files have the same destination: {target}")
        seen.add(key)
        updated = dict(action)
        updated["new_path"] = str(target)
        updated["category"] = category
        updated["subcategory"] = organizer.taxonomy.subcategory(category, sub) if category else ""
        organizer._validate_plan_paths(updated, require_source=False)
        if target.resolve(strict=False) != old.resolve(strict=False):
            selected.append(updated)
    return selected


def preflight_review(organizer, actions: List[Dict[str, Any]]) -> None:
    organizer.planned_actions = list(actions)
    organizer._preflight_plan()



def manual_review_action(
    organizer, queued: Mapping[str, Any], filename: str,
    category: str, subcategory: str = ""
) -> Dict[str, Any]:
    """Create a fingerprinted, explicitly authorized action for a queued file."""
    source_value = queued.get("path", "")
    if not isinstance(source_value, str):
        raise ValueError("Queued path is invalid.")
    source = Path(source_value)
    if (
        not source.is_absolute()
        or source.is_symlink()
        or not source.is_file()
        or not organizer._path_is_within(source, organizer.root_folder)
    ):
        raise ValueError("Queued source is missing or outside the selected folder.")

    fingerprint = organizer._file_fingerprint(source)
    if queued.get("sha256") and fingerprint["sha256"] != queued["sha256"]:
        raise ValueError("Queued source has changed; analyze it again before moving.")

    if (
        not isinstance(filename, str)
        or not filename
        or "/" in filename or "\\" in filename
        or filename != Path(filename).name
        or filename != organizer.sanitize_filename(filename, max_len=255)
        or not filename.lower().endswith(source.suffix.lower())
    ):
        raise ValueError("Reviewed filename is unsafe or changes the extension.")

    folder = organizer.taxonomy.target_dir(
        organizer.root_folder, organizer.organize_folder_name, category, subcategory
    )
    action = {
        "old_path": str(source.resolve()),
        "new_path": str((folder / filename).resolve(strict=False)),
        "category": organizer.taxonomy.category(category),
        "subcategory": organizer.taxonomy.subcategory(category, subcategory),
        "reason": "Manually reviewed and approved",
        "source": "manual",
        "source_fingerprint": fingerprint,
    }
    organizer._validate_plan_paths(action, require_source=True)
    return action
