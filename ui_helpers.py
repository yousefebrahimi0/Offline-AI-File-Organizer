"""Validated, framework-independent plan editing for the local review interface."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


def review_rows(actions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create an editable table without exposing mutable file paths."""
    return [
        {
            "Apply": True,
            "Original": Path(a["old_path"]).name,
            "New filename": Path(a["new_path"]).name,
            "Category": a.get("category", ""),
        }
        for a in actions
    ]


def select_reviewed_actions(
    organizer, original: List[Dict[str, Any]], edited: Iterable[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Only permit destination filename/category edits within the original root.

    The approved original file path and SHA-256 fingerprint are never editable.
    Revalidation before any move is done by FileOrganizer._preflight_plan.
    """
    rows = list(edited)
    if len(rows) != len(original):
        raise ValueError("The review table differs in length from the original plan.")

    selected: List[Dict[str, Any]] = []
    seen = set()
    categories = set(organizer.categories)
    for action, row in zip(original, rows):
        if not bool(row.get("Apply", False)):
            continue

        old = Path(action["old_path"])
        proposed = Path(action["new_path"])
        filename = row.get("New filename")
        category = row.get("Category", "")

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
            if category not in categories:
                raise ValueError(f"Category is not configured: {category}")
            target_dir = organizer.root_folder / organizer.organize_folder_name / category
        else:
            if category:
                raise ValueError("Categories cannot be added to a rename-only plan.")
            target_dir = proposed.parent

        target = target_dir / filename
        target_key = os.path.normcase(str(target.resolve(strict=False)))
        if target_key in seen:
            raise ValueError(f"Two reviewed files have the same destination: {target}")
        seen.add(target_key)

        updated = dict(action)
        updated["new_path"] = str(target)
        updated["category"] = category
        organizer._validate_plan_paths(updated, require_source=False)
        if target.resolve(strict=False) == old.resolve(strict=False):
            continue
        selected.append(updated)

    return selected


def preflight_review(organizer, actions: List[Dict[str, Any]]) -> None:
    """Validate all selected operations without modifying any source files."""
    organizer.planned_actions = list(actions)
    organizer._preflight_plan()
