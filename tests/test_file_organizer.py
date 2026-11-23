import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from file_organizer import FileOrganizer, UniversalLLMClient, load_config


class FakeLLM(UniversalLLMClient):
    def __init__(self, responses):
        super().__init__(provider="lm_studio", model="test-model")
        self.responses = list(responses)
        self.calls = 0

    def test_connection(self):
        return True, "Connected to fake"

    def chat(self, prompt: str):
        self.calls += 1
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


def test_cached_dry_run_and_undo(tmp_path):
    f1 = tmp_path / "notes.txt"
    f1.write_text("Project Alpha architecture notes", encoding="utf-8")

    fake_llm = FakeLLM(['{"filename": "Project Alpha Architecture", "category": "Projects"}'])
    organizer = FileOrganizer(str(tmp_path), llm_client=fake_llm)

    plan = organizer.build_plan(rename=True, organize=True)
    assert len(plan) == 1
    assert fake_llm.calls == 1

    log_file = organizer.apply_plan(save_log=True)
    assert fake_llm.calls == 1  # No second LLM call!
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
