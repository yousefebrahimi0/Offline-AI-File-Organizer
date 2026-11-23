"""Smoke-test the actual Streamlit rendering on the dedicated GUI CI job."""

import pytest


def test_streamlit_dashboard_renders():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file("web_app.py", default_timeout=15).run()
    assert not app.exception
    assert len(app.title) >= 1
