"""GUI plan-editing, package launcher and basic lifecycle regressions."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from file_organizer import FileOrganizer
from ui_helpers import preflight_review, review_rows, select_reviewed_actions


def prepared(tmp_path):
    original = tmp_path / "invoice.txt"
    original.write_text("Payment for a service", encoding="utf-8")
    organizer = FileOrganizer(str(tmp_path))
    action = {
        "old_path": str(original),
        "new_path": str(tmp_path / "Organized" / "Finance" / "Invoice.txt"),
        "category": "Finance",
        "source_fingerprint": organizer._file_fingerprint(original),
    }
    return organizer, original, action


def test_review_can_skip_without_touching_source(tmp_path):
    organizer, original, action = prepared(tmp_path)
    rows = review_rows([action])
    rows[0]["Apply"] = False
    assert select_reviewed_actions(organizer, [action], rows) == []
    assert original.exists()


def test_review_can_edit_category_and_name_within_root(tmp_path):
    organizer, original, action = prepared(tmp_path)
    rows = review_rows([action])
    rows[0]["Category"] = "Projects"
    rows[0]["New filename"] = "New Invoice.txt"
    selected = select_reviewed_actions(organizer, [action], rows)
    assert len(selected) == 1
    assert selected[0]["new_path"] == str(tmp_path / "Organized" / "Projects" / "New Invoice.txt")
    assert selected[0]["source_fingerprint"] == action["source_fingerprint"]
    preflight_review(organizer, selected)
    assert original.exists()


@pytest.mark.parametrize("filename", ["../escaped.txt", "/tmp/bad.txt", "nested/name.txt",
                                      "invoice.pdf", "bad:invoice.txt", ""])
def test_review_rejects_unsafe_names(tmp_path, filename):
    organizer, original, action = prepared(tmp_path)
    rows = review_rows([action])
    rows[0]["New filename"] = filename
    with pytest.raises(ValueError):
        select_reviewed_actions(organizer, [action], rows)


def test_review_rejects_unconfigured_category(tmp_path):
    organizer, original, action = prepared(tmp_path)
    rows = review_rows([action])
    rows[0]["Category"] = "../../private"
    with pytest.raises(ValueError):
        select_reviewed_actions(organizer, [action], rows)


def test_review_rejects_duplicate_targets(tmp_path):
    organizer, first, action = prepared(tmp_path)
    second = tmp_path / "other.txt"
    second.write_text("Other", encoding="utf-8")
    other = dict(action, old_path=str(second), source_fingerprint=organizer._file_fingerprint(second))
    with pytest.raises(ValueError, match="same destination"):
        select_reviewed_actions(organizer, [action, other], review_rows([action, other]))


def test_review_preflight_detects_source_mutation(tmp_path):
    organizer, original, action = prepared(tmp_path)
    original.write_text("new contents", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        preflight_review(organizer, [action])


def test_gui_module_imports_without_streamlit():
    import web_app
    import gui_launcher
    assert callable(web_app.render)
    assert callable(gui_launcher.main)


def test_watch_controller_stats_and_shutdown(tmp_path):
    from ui_watch import WatchController
    organizer = FileOrganizer(str(tmp_path))
    controller = WatchController(organizer, workers=1, stability_seconds=0)
    assert controller.stats()["events"] == 0
    result = controller.stop()
    assert result["stats"]["moved"] == 0
