"""Smart Organization v3: regression and safety tests without real AI calls."""

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from document_intelligence import optimized_image
from file_organizer import FileOrganizer, load_config
from smart_organizer import DuplicateIndex, ReviewQueue, RuleBook, Taxonomy, Workspace
from ui_helpers import review_rows, select_reviewed_actions


class LLM:
    provider = "fake"

    def __init__(self, response=None):
        self.response = response
        self.calls = 0
        self.last_image = None

    def chat(self, prompt, image_path=None):
        self.calls += 1
        self.last_image = image_path
        return self.response


def make_organizer(tmp_path, response=None, overrides=None):
    cfg = load_config()
    cfg["organizer"].update(overrides or {})
    return FileOrganizer(str(tmp_path), config=cfg, llm_client=LLM(response))


def test_smart_profile_routes_only_approved_two_levels(tmp_path):
    f = tmp_path / "invoice.txt"
    f.write_text("Invoice ACME total 10 EUR", encoding="utf-8")
    organizer = make_organizer(
        tmp_path,
        '{"filename":"November Invoice","category":"Finance","subcategory":"Invoices","reason":"Contains invoice total"}',
    )
    actions = organizer.build_plan(rename=True, organize=True)
    assert len(actions) == 1
    action = actions[0]
    assert Path(action["new_path"]).parent == tmp_path / "Organized" / "Finance" / "Invoices"
    assert action["reason"] == "Contains invoice total"
    assert action["source"] == "ai"
    assert not (tmp_path / "Organized").exists()


def test_simple_profile_ignores_subcategory_and_limits_depth(tmp_path):
    f = tmp_path / "invoice.txt"
    f.write_text("Invoice ACME", encoding="utf-8")
    organizer = make_organizer(
        tmp_path,
        '{"filename":"November Invoice","category":"Finance","subcategory":"Invoices"}',
        {"profile": "simple"},
    )
    actions = organizer.build_plan(rename=True, organize=True)
    assert len(actions) == 1
    assert Path(actions[0]["new_path"]).parent == tmp_path / "Organized" / "Finance"


def test_unknown_category_goes_to_review_queue_without_moving(tmp_path):
    f = tmp_path / "mystery.txt"
    f.write_text("Sensitive unknown contents", encoding="utf-8")
    organizer = make_organizer(
        tmp_path,
        '{"filename":"Mystery Note","category":"Everything Else","subcategory":""}',
    )
    assert organizer.build_plan(rename=True, organize=True) == []
    assert f.exists()
    queue = organizer.review_queue.items()
    assert len(queue) == 1
    assert queue[0]["path"] == str(f)
    assert "outside approved" in queue[0]["reason"]


def test_unknown_subcategory_goes_to_queue(tmp_path):
    f = tmp_path / "invoice.txt"
    f.write_text("Invoice ACME", encoding="utf-8")
    organizer = make_organizer(
        tmp_path,
        '{"filename":"Invoice","category":"Finance","subcategory":"Future/2026"}',
    )
    assert organizer.build_plan(rename=True, organize=True) == []
    assert "subcategory" in organizer.review_queue.items()[0]["reason"]


def test_rules_skip_model_calls_and_persist(tmp_path):
    f = tmp_path / "november_invoice.pdf"
    f.write_text("invoice", encoding="utf-8")
    organizer = make_organizer(tmp_path, overrides={"profile":"smart"})
    organizer.rulebook.add({"pattern":"*invoice.pdf","category":"Finance","subcategory":"Invoices"})
    actions = organizer.build_plan(rename=True, organize=True)
    assert len(actions) == 1
    assert organizer.llm.calls == 0
    assert actions[0]["source"] == "rule"
    assert "Invoices" in Path(actions[0]["new_path"]).parts
    assert (tmp_path / ".organizer" / "rules.json").exists()


def test_rules_need_matching_content_when_contains_requested(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("Monthly bill from ACME", encoding="utf-8")
    organizer = make_organizer(
        tmp_path,
        '{"filename":"ACME Note","category":"Personal","subcategory":""}',
    )
    organizer.rulebook.add({
        "pattern": "*.txt", "contains": "absent",
        "category": "Finance", "subcategory": "Invoices",
    })
    actions = organizer.build_plan(rename=True, organize=True)
    assert len(actions) == 1
    assert actions[0]["category"] == "Personal"
    assert organizer.llm.calls == 1


def test_duplicate_content_is_queued_and_second_file_not_analyzed(tmp_path):
    (tmp_path / "a.txt").write_text("Exactly identical contents", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Exactly identical contents", encoding="utf-8")
    organizer = make_organizer(
        tmp_path,
        '{"filename":"Text Notes","category":"Projects","subcategory":""}',
    )
    actions = organizer.build_plan(rename=True, organize=True)
    assert len(actions) == 1
    assert organizer.llm.calls == 1
    assert (tmp_path / "b.txt").exists()
    items = organizer.review_queue.items()
    assert len(items) == 1
    assert "Identical file" in items[0]["reason"]


def test_duplicate_of_organized_file_skips_model(tmp_path):
    old = tmp_path / "Organized" / "Finance" / "receipt.txt"
    old.parent.mkdir(parents=True)
    old.write_text("Same document", encoding="utf-8")
    incoming = tmp_path / "incoming.txt"
    incoming.write_text("Same document", encoding="utf-8")
    organizer = make_organizer(tmp_path)
    assert organizer.build_plan(rename=True, organize=True) == []
    assert organizer.llm.calls == 0
    assert incoming.exists()


def test_workspace_is_not_scanned(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("Invoice", encoding="utf-8")
    organizer = make_organizer(tmp_path)
    organizer.review_queue.add(f, "Needs manual check")
    (tmp_path / ".organizer" / "do_not_touch.txt").write_text("data")
    assert organizer.discover_files() == [f]


def test_review_queue_dismiss_and_persistence(tmp_path):
    workspace = Workspace(tmp_path)
    queue = ReviewQueue(workspace)
    file_path = tmp_path / "x.pdf"
    queue.add(file_path, "No OCR")
    assert len(ReviewQueue(workspace).items()) == 1
    queue.dismiss(str(file_path))
    assert queue.items() == []


@pytest.mark.parametrize("unsafe", ["../outside", "Finance/2026", "X\\Y", "", "..", "A:B"])
def test_taxonomy_rejects_unsafe_subfolders(unsafe):
    with pytest.raises(ValueError):
        Taxonomy(["Finance"], "custom", {"Finance":[unsafe]})


def test_reviewed_subcategory_cannot_escape_allowed_tree(tmp_path):
    source = tmp_path / "invoice.txt"
    source.write_text("Invoice", encoding="utf-8")
    organizer = make_organizer(tmp_path)
    action = {
        "old_path":str(source),
        "new_path":str(tmp_path/"Organized"/"Finance"/"Invoices"/"Invoice.txt"),
        "category":"Finance",
        "subcategory":"Invoices",
        "source_fingerprint":organizer._file_fingerprint(source),
    }
    rows = review_rows([action])
    rows[0]["Subcategory"] = "../../private"
    with pytest.raises(ValueError, match="subcategor"):
        select_reviewed_actions(organizer, [action], rows)
    rows[0]["Subcategory"] = "Receipts"
    selected = select_reviewed_actions(organizer, [action], rows)
    assert Path(selected[0]["new_path"]).parent == tmp_path/"Organized"/"Finance"/"Receipts"


def test_naming_templates_and_unknown_fields_rejected(tmp_path):
    source = tmp_path / "hello.txt"
    source.write_text("hello")
    organizer = make_organizer(tmp_path, overrides={"naming_template":"{date} - {title}"})
    assert organizer.format_target_name("Hello",source).endswith("- Hello.txt")
    organizer.naming_template = "{title}{__class__}"
    with pytest.raises(ValueError):
        organizer.format_target_name("Hello",source)


def test_pdf_ocr_fallback_is_used_for_scanned_document(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF simulated")
    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""
    reader = MagicMock()
    reader.pages = [mock_page]
    organizer = make_organizer(tmp_path)
    with patch("file_organizer.PdfReader",return_value=reader), \
         patch("file_organizer.scanned_pdf_ocr",return_value="Invoice OCR extracted") as ocr:
        content = organizer.extract_text_content(source)
    assert "Invoice OCR extracted" in content
    ocr.assert_called_once_with(source)


def test_pdf_text_preferred_over_ocr(tmp_path):
    source = tmp_path / "digital.pdf"
    source.write_bytes(b"%PDF simulated")
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Embedded digital text"
    reader = MagicMock()
    reader.pages = [mock_page]
    organizer = make_organizer(tmp_path)
    with patch("file_organizer.PdfReader",return_value=reader), \
         patch("file_organizer.scanned_pdf_ocr") as ocr:
        content = organizer.extract_text_content(source)
    assert "Embedded digital text" in content
    ocr.assert_not_called()


def test_optimized_image_is_in_memory_and_does_not_modify_original(tmp_path):
    pil = pytest.importorskip("PIL")
    from PIL import Image
    file_path = tmp_path/"image.png"
    Image.new("RGB",(2400,1800),color=(40, 70, 110)).save(file_path)
    original = file_path.read_bytes()
    mime,data = optimized_image(file_path,max_dimension=1024,quality=65)
    assert mime == "image/jpeg"
    assert data
    assert file_path.read_bytes() == original
    import io
    with Image.open(io.BytesIO(base64.b64decode(data))) as resized:
        assert max(resized.size) <= 1024


def test_model_uses_ocr_instead_of_vision_if_text_is_long_enough(tmp_path):
    source = tmp_path/"receipt.jpg"
    source.write_bytes(b"jpeg placeholder")
    organizer = make_organizer(
        tmp_path,'{"filename":"Receipt","category":"Finance","subcategory":"Receipts"}',
        {"enable_images":True,"ocr_first_images":True}
    )
    with patch("file_organizer.image_ocr",return_value="STORE RECEIPT CUSTOMER DATE 2026 TOTAL 12.50 EUR"):
        result=organizer.suggest_file(source,rename=True,organize=True)
    assert result["category"] == "Finance"
    assert organizer.llm.last_image is None


def test_rule_pattern_must_not_be_directory_traversal(tmp_path):
    organizer = make_organizer(tmp_path)
    with pytest.raises(ValueError):
        organizer.rulebook.add({"pattern":"../*.pdf","category":"Finance"})


def test_apply_and_undo_two_level_plan(tmp_path):
    source = tmp_path / "invoice.txt"
    source.write_text("Invoice 2026",encoding="utf-8")
    organizer = make_organizer(
        tmp_path,
        '{"filename":"November Invoice","category":"Finance","subcategory":"Invoices"}'
    )
    plan=organizer.build_plan(rename=True,organize=True)
    log=organizer.apply_plan()
    assert len(plan)==1
    assert Path(plan[0]["new_path"]).exists()
    assert log and log.exists()
    assert FileOrganizer.undo_from_log(str(log))==1
    assert source.exists()



def test_cache_prevents_repeated_llm_calls_and_persists(tmp_path):
    source = tmp_path / "project.txt"
    source.write_text("A very interesting project idea", encoding="utf-8")
    organizer = make_organizer(
        tmp_path, '{"filename":"Project Idea","category":"Projects","subcategory":"Plans"}'
    )
    first = organizer.suggest_file(source)
    second = organizer.suggest_file(source)
    assert first["category"] == second["category"] == "Projects"
    assert second["source"] == "cache"
    assert organizer.llm.calls == 1

    again = make_organizer(tmp_path)
    cached = again.suggest_file(source)
    assert cached["source"] == "cache"
    assert again.llm.calls == 0
    assert (tmp_path / ".organizer" / "analysis_cache.json").exists()


def test_cache_invalidates_when_file_changes(tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("First contents", encoding="utf-8")
    organizer = make_organizer(
        tmp_path, '{"filename":"Note","category":"Personal","subcategory":""}'
    )
    organizer.suggest_file(source)
    source.write_text("Updated contents", encoding="utf-8")
    organizer.suggest_file(source)
    assert organizer.llm.calls == 2


def test_cache_can_be_disabled(tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("Contents", encoding="utf-8")
    organizer = make_organizer(
        tmp_path, '{"filename":"Note","category":"Personal","subcategory":""}',
        {"cache_ai_results": False}
    )
    organizer.suggest_file(source)
    organizer.suggest_file(source)
    assert organizer.llm.calls == 2


def test_local_document_metadata_hints_and_filename(tmp_path):
    from document_intelligence import document_hints
    text = "Supplier: ACME Tools\nDate: 2026-11-22\nInvoice no: 987X"
    hints = document_hints(text)
    assert hints["document_date"] == "2026-11-22"
    assert hints["vendor"].startswith("ACME Tools")
    organizer = make_organizer(
        tmp_path, overrides={"naming_template":"{document_date} - {vendor} - {title}"}
    )
    source = tmp_path / "invoice.txt"
    source.write_text("Invoice")
    assert organizer.format_target_name("Invoice",source,"Finance",**{
        "document_date":hints["document_date"],"vendor":hints["vendor"]
    }) == "2026-11-22 - ACME Tools - Invoice.txt"


def test_manual_review_action_is_safe_and_undoable(tmp_path):
    from ui_helpers import manual_review_action
    source = tmp_path / "uncertain.txt"
    source.write_text("A private document", encoding="utf-8")
    organizer = make_organizer(tmp_path)
    fingerprint = organizer._file_fingerprint(source)
    queued = {"path":str(source), "sha256":fingerprint["sha256"]}
    action = manual_review_action(organizer,queued,"Reviewed.txt","Personal","Legal")
    assert action["source"] == "manual"
    organizer.planned_actions=[action]
    log=organizer.apply_plan(save_log=True)
    assert Path(action["new_path"]).exists()
    assert log and log.exists()
    assert FileOrganizer.undo_from_log(str(log))==1
    assert source.exists()


def test_manual_review_refuses_changed_queue_item(tmp_path):
    from ui_helpers import manual_review_action
    source = tmp_path / "uncertain.txt"
    source.write_text("Original", encoding="utf-8")
    organizer = make_organizer(tmp_path)
    old_fingerprint = organizer._file_fingerprint(source)
    source.write_text("Changed", encoding="utf-8")
    with pytest.raises(ValueError, match="has changed"):
        manual_review_action(
            organizer,{"path":str(source),"sha256":old_fingerprint["sha256"]},
            "New.txt","Personal",""
        )


def test_no_ai_miscellaneous_fallback_for_uncertain_results(tmp_path):
    source = tmp_path / "mystery.txt"
    source.write_text("Hard to identify", encoding="utf-8")
    organizer = make_organizer(
        tmp_path, '{"filename":"Mystery","category":"Miscellaneous","subcategory":""}'
    )
    assert organizer.build_plan(rename=True,organize=True)==[]
    assert source.exists()
    assert len(organizer.review_queue.items())==1



def test_category_only_plan_does_not_allow_unapproved_nesting(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("Plan", encoding="utf-8")
    organizer = make_organizer(tmp_path)
    action = {
        "old_path": str(f),
        "new_path": str(tmp_path / "Organized" / "Projects" / "2026" / "note.txt"),
        "category": "Projects", "subcategory": "",
        "source_fingerprint": organizer._file_fingerprint(f),
    }
    organizer.planned_actions = [action]
    with pytest.raises(ValueError, match="approved folder depth"):
        organizer.apply_plan()
    assert f.exists()


def test_rename_only_plan_does_not_move_between_folders(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("Plan", encoding="utf-8")
    organizer = make_organizer(tmp_path)
    action = {
        "old_path": str(f),
        "new_path": str(tmp_path / "private" / "renamed.txt"),
        "category": "", "subcategory": "",
        "source_fingerprint": organizer._file_fingerprint(f),
    }
    organizer.planned_actions = [action]
    with pytest.raises(ValueError, match="Rename-only"):
        organizer.apply_plan()
    assert f.exists()


def test_duplicate_index_tracks_organizer_move(tmp_path):
    first = tmp_path / "first.txt"
    first.write_text("Same material", encoding="utf-8")
    organizer = make_organizer(
        tmp_path, '{"filename":"Text","category":"Projects","subcategory":""}'
    )
    plan = organizer.build_plan(rename=True, organize=True)
    organizer.apply_plan()
    assert Path(plan[0]["new_path"]).exists()

    later = tmp_path / "later.txt"
    later.write_text("Same material", encoding="utf-8")
    assert organizer.build_plan(rename=True, organize=True) == []
    assert len(organizer.review_queue.items()) >= 1
    assert later.exists()
