import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from file_organizer import FileOrganizer, UniversalLLMClient, load_config


class FakeLLM(UniversalLLMClient):
    def __init__(self, responses):
        super().__init__(provider="lm_studio", model="test-model")
        self.responses = list(responses)
        self.calls = 0
        self.last_image_path = None

    def test_connection(self):
        return True, "Connected to fake"

    def chat(self, prompt: str, image_path=None):
        self.calls += 1
        self.last_image_path = image_path
        return self.responses.pop(0) if self.responses else None


def test_excludes_organized_folder(tmp_path):
    (tmp_path / "doc1.txt").write_text("Quarterly finance report", encoding="utf-8")
    org_dir = tmp_path / "Organized" / "Finance"
    org_dir.mkdir(parents=True)
    (org_dir / "already_sorted.txt").write_text("Old report", encoding="utf-8")

    organizer = FileOrganizer(str(tmp_path), llm_client=FakeLLM([]))
    discovered = organizer.discover_files()
    assert [p.name for p in discovered] == ["doc1.txt"]


def test_sanitize_category_prevents_path_traversal(tmp_path):
    organizer = FileOrganizer(str(tmp_path), llm_client=FakeLLM([]))
    assert organizer.sanitize_category("../../etc/passwd") == "Miscellaneous"
    assert organizer.sanitize_category("Category: Finance!") == "Finance"
    assert organizer.sanitize_category("legal") == "Legal"


def test_cached_dry_run_save_apply_and_undo(tmp_path):
    f1 = tmp_path / "notes.txt"
    f1.write_text("Project Alpha architecture notes", encoding="utf-8")

    fake_llm = FakeLLM(['{"filename": "Project Alpha Architecture", "category": "Projects"}'])
    organizer = FileOrganizer(str(tmp_path), llm_client=fake_llm)

    plan = organizer.build_plan(rename=True, organize=True)
    assert len(plan) == 1
    assert fake_llm.calls == 1

    plan_file = tmp_path / "plan.json"
    organizer.save_plan(str(plan_file))
    assert plan_file.exists()

    organizer2 = FileOrganizer(str(tmp_path), llm_client=fake_llm)
    organizer2.load_plan(str(plan_file))
    log_file = organizer2.apply_plan(save_log=True)

    assert fake_llm.calls == 1
    assert not f1.exists()
    new_path = Path(plan[0]["new_path"])
    assert new_path.exists()
    assert new_path.parent.name == "Projects"
    assert log_file and log_file.exists()

    restored = FileOrganizer.undo_from_log(str(log_file))
    assert restored == 1
    assert f1.exists()
    assert not new_path.exists()


def test_pdf_none_text_does_not_crash(tmp_path):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")

    mock_page = MagicMock()
    mock_page.extract_text.return_value = None
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    organizer = FileOrganizer(str(tmp_path), llm_client=FakeLLM([]))
    with patch("file_organizer.PdfReader", return_value=mock_reader):
        content = organizer.extract_text_content(pdf_path)
    assert content == "File: scan"


def test_rtf_odt_pptx_extractors(tmp_path):
    organizer = FileOrganizer(str(tmp_path), llm_client=FakeLLM([]))

    rtf_path = tmp_path / "memo.rtf"
    rtf_path.write_text(r"{\rtf1\ansi Hello \b World\b0 from RTF}", encoding="utf-8")
    assert "Hello" in organizer.extract_text_content(rtf_path)
    assert "World" in organizer.extract_text_content(rtf_path)

    odt_path = tmp_path / "doc.odt"
    with zipfile.ZipFile(odt_path, "w") as zf:
        zf.writestr("content.xml", "<office:text xmlns:office=\"urn:oasis:names:tc:opendocument:xmlns:office:1.0\" xmlns:text=\"urn:oasis:names:tc:opendocument:xmlns:text:1.0\"><text:p>ODT Invoice 2026</text:p></office:text>")
    assert "ODT Invoice 2026" in organizer.extract_text_content(odt_path)

    pptx_path = tmp_path / "deck.pptx"
    with zipfile.ZipFile(pptx_path, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", "<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\"><a:t>Startup Pitch Deck</a:t></p:sld>")
    assert "Startup Pitch Deck" in organizer.extract_text_content(pptx_path)


def test_image_vision_routing(tmp_path):
    img_path = tmp_path / "receipt.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    cfg = load_config()
    cfg["organizer"]["enable_images"] = True
    cfg["organizer"]["use_vision_model"] = True

    fake_llm = FakeLLM(['{"filename": "Coffee Shop Receipt", "category": "Finance"}'])
    organizer = FileOrganizer(str(tmp_path), llm_client=fake_llm, config=cfg)

    discovered = organizer.discover_files()
    assert [p.name for p in discovered] == ["receipt.png"]

    name, category = organizer.analyze_file(img_path, rename=True, organize=True)
    assert name == "Coffee Shop Receipt"
    assert category == "Finance"
    assert fake_llm.last_image_path == img_path


def test_universal_llm_auto_model_detection():
    client = UniversalLLMClient(provider="ollama", model="auto")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "qwen2.5:7b"}, {"id": "llama3.2"}]}

    with patch("file_organizer.requests.get", return_value=mock_resp):
        ok, msg = client.test_connection()
    assert ok is True
    assert client.model == "qwen2.5:7b"
    assert "qwen2.5:7b" in msg



def test_ai_failure_does_not_plan_miscellaneous_move(tmp_path):
    source = tmp_path / "unreadable.txt"
    source.write_text("Important document", encoding="utf-8")
    organizer = FileOrganizer(str(tmp_path), llm_client=FakeLLM([None]))
    assert organizer.build_plan(rename=True, organize=True) == []
    assert source.exists()
    assert not (tmp_path / "Organized" / "Miscellaneous").exists()


def test_saved_plan_rejects_changed_source_file(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Original contents", encoding="utf-8")
    organizer = FileOrganizer(
        str(tmp_path),
        llm_client=FakeLLM(['{"filename": "Project Notes", "category": "Projects"}']),
    )
    organizer.build_plan(rename=True, organize=True)
    plan_file = tmp_path / "plan.json"
    organizer.save_plan(str(plan_file))

    source.write_text("Changed contents after approval", encoding="utf-8")
    organizer2 = FileOrganizer(str(tmp_path), llm_client=FakeLLM([]))
    organizer2.load_plan(str(plan_file))
    with pytest.raises(ValueError, match="changed since the plan"):
        organizer2.apply_plan()
    assert source.read_text(encoding="utf-8") == "Changed contents after approval"


def test_apply_plan_never_overwrites_existing_destination(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Original contents", encoding="utf-8")
    organizer = FileOrganizer(
        str(tmp_path),
        llm_client=FakeLLM(['{"filename": "Project Notes", "category": "Projects"}']),
    )
    plan = organizer.build_plan(rename=True, organize=True)
    target = Path(plan[0]["new_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("User's newer file", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Destination already exists"):
        organizer.apply_plan()
    assert source.read_text(encoding="utf-8") == "Original contents"
    assert target.read_text(encoding="utf-8") == "User's newer file"


def test_load_plan_rejects_path_outside_root(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Original contents", encoding="utf-8")
    organizer = FileOrganizer(
        str(tmp_path),
        llm_client=FakeLLM(['{"filename": "Project Notes", "category": "Projects"}']),
    )
    organizer.build_plan(rename=True, organize=True)
    plan_file = tmp_path / "plan.json"
    organizer.save_plan(str(plan_file))
    plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
    plan_data["actions"][0]["new_path"] = str(tmp_path.parent / "outside.txt")
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    organizer2 = FileOrganizer(str(tmp_path), llm_client=FakeLLM([]))
    with pytest.raises(ValueError, match="escapes the selected folder"):
        organizer2.load_plan(str(plan_file))


def test_undo_does_not_overwrite_recreated_original(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Original contents", encoding="utf-8")
    organizer = FileOrganizer(
        str(tmp_path),
        llm_client=FakeLLM(['{"filename": "Project Notes", "category": "Projects"}']),
    )
    plan = organizer.build_plan(rename=True, organize=True)
    log_file = organizer.apply_plan(save_log=True)
    target = Path(plan[0]["new_path"])
    assert log_file and target.exists()
    source.write_text("A different file created after the move", encoding="utf-8")

    assert FileOrganizer.undo_from_log(str(log_file)) == 0
    assert source.read_text(encoding="utf-8") == "A different file created after the move"
    assert target.read_text(encoding="utf-8") == "Original contents"


def test_undo_skips_file_modified_after_organization(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Original contents", encoding="utf-8")
    organizer = FileOrganizer(
        str(tmp_path),
        llm_client=FakeLLM(['{"filename": "Project Notes", "category": "Projects"}']),
    )
    plan = organizer.build_plan(rename=True, organize=True)
    log_file = organizer.apply_plan(save_log=True)
    target = Path(plan[0]["new_path"])
    target.write_text("Edited after organization", encoding="utf-8")

    assert FileOrganizer.undo_from_log(str(log_file)) == 0
    assert target.read_text(encoding="utf-8") == "Edited after organization"
    assert not source.exists()


def test_load_plan_rejects_wrong_root_and_legacy_unsafe_plan(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Original contents", encoding="utf-8")
    organizer = FileOrganizer(
        str(tmp_path),
        llm_client=FakeLLM(['{"filename": "Project Notes", "category": "Projects"}']),
    )
    organizer.build_plan(rename=True, organize=True)
    plan_file = tmp_path / "plan.json"
    organizer.save_plan(str(plan_file))

    wrong_root = FileOrganizer(str(tmp_path.parent), llm_client=FakeLLM([]))
    with pytest.raises(ValueError, match="different folder"):
        wrong_root.load_plan(str(plan_file))

    legacy_file = tmp_path / "legacy-plan.json"
    legacy_file.write_text(
        json.dumps({"version": 2, "root_folder": str(tmp_path), "actions": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported or unsafe plan format"):
        organizer.load_plan(str(legacy_file))



def test_watch_mode_saves_review_plan_without_moving_files(tmp_path):
    from watch_folder import WatchFolderService

    source = tmp_path / "incoming.txt"
    source.write_text("A new project note", encoding="utf-8")
    organizer = FileOrganizer(
        str(tmp_path),
        llm_client=FakeLLM(['{"filename": "New Project Note", "category": "Projects"}']),
    )
    service = WatchFolderService(organizer, workers=1, stability_seconds=0, poll_interval=0.01)
    assert service.submit(source) is True
    result = service.shutdown()

    assert source.exists()
    assert result["plan_path"] is not None
    plan_data = json.loads(result["plan_path"].read_text(encoding="utf-8"))
    assert plan_data["version"] == 3
    assert len(plan_data["actions"]) == 1
    assert result["stats"]["planned"] == 1


def test_watch_mode_auto_apply_writes_undo_log(tmp_path):
    from watch_folder import WatchFolderService

    source = tmp_path / "incoming.txt"
    source.write_text("A new project note", encoding="utf-8")
    organizer = FileOrganizer(
        str(tmp_path),
        llm_client=FakeLLM(['{"filename": "New Project Note", "category": "Projects"}']),
    )
    service = WatchFolderService(
        organizer, workers=1, stability_seconds=0, poll_interval=0.01, auto_apply=True
    )
    assert service.submit(source) is True
    result = service.shutdown()

    assert not source.exists()
    assert result["log_path"] is not None
    log_data = json.loads(result["log_path"].read_text(encoding="utf-8"))
    target = Path(log_data["actions"][0]["new_path"])
    assert target.exists()
    assert FileOrganizer.undo_from_log(str(result["log_path"])) == 1
    assert source.exists()


def test_watch_mode_coalesces_duplicate_events(tmp_path):
    import threading
    from watch_folder import WatchFolderService

    started = threading.Event()
    release = threading.Event()

    class BlockingLLM:
        provider = "fake"
        def __init__(self):
            self.calls = 0
        def chat(self, prompt, image_path=None):
            self.calls += 1
            started.set()
            assert release.wait(timeout=5)
            return '{"filename": "Stable Note", "category": "Projects"}'

    source = tmp_path / "incoming.txt"
    source.write_text("A stable document", encoding="utf-8")
    llm = BlockingLLM()
    organizer = FileOrganizer(str(tmp_path), llm_client=llm)
    service = WatchFolderService(organizer, workers=1, stability_seconds=0, poll_interval=0.01)

    assert service.submit(source) is True
    assert started.wait(timeout=5)
    assert service.submit(source) is False
    release.set()
    result = service.shutdown()

    assert llm.calls == 1
    assert result["stats"]["events"] == 2
    assert result["stats"]["planned"] == 1


def test_watch_mode_parallelizes_analysis_with_worker_limit(tmp_path):
    import threading
    import time
    from watch_folder import WatchFolderService

    class ParallelLLM:
        provider = "fake"
        def __init__(self):
            self.active = 0
            self.maximum = 0
            self.lock = threading.Lock()
        def chat(self, prompt, image_path=None):
            with self.lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            time.sleep(0.12)
            with self.lock:
                self.active -= 1
            return '{"filename": "Parallel Analysis", "category": "Projects"}'

    for filename in ("one.txt", "two.txt", "three.txt"):
        (tmp_path / filename).write_text(filename, encoding="utf-8")
    llm = ParallelLLM()
    organizer = FileOrganizer(str(tmp_path), llm_client=llm)
    service = WatchFolderService(organizer, workers=2, stability_seconds=0, poll_interval=0.01)
    for filename in ("one.txt", "two.txt", "three.txt"):
        assert service.submit(tmp_path / filename) is True
    result = service.shutdown()

    assert llm.maximum == 2
    assert result["stats"]["planned"] == 3
    assert result["plan_path"] is not None


def test_watch_mode_ignores_organized_and_unsupported_files(tmp_path):
    from watch_folder import WatchFolderService

    organized = tmp_path / "Organized" / "Projects" / "old.txt"
    organized.parent.mkdir(parents=True)
    organized.write_text("Already organized", encoding="utf-8")
    unsupported = tmp_path / "video.mp4"
    unsupported.write_text("not supported", encoding="utf-8")
    organizer = FileOrganizer(str(tmp_path), llm_client=FakeLLM([]))
    service = WatchFolderService(organizer, workers=1, stability_seconds=0, poll_interval=0.01)

    assert service.submit(organized) is False
    assert service.submit(unsupported) is False
    result = service.shutdown()
    assert result["stats"]["planned"] == 0
    assert result["plan_path"] is None
