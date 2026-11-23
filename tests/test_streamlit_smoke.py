"""Smoke-test the actual Streamlit rendering on the dedicated GUI CI job."""

from pathlib import Path

import pytest


def test_streamlit_dashboard_renders():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "web_app.py", default_timeout=15).run()
    assert not app.exception
    assert len(app.title) >= 1
