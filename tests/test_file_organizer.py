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
