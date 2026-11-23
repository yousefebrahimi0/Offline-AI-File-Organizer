"""Launch the bundled local-only Streamlit interface."""

from pathlib import Path


def main():
    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:
        raise SystemExit(
            "The web UI is optional. Install it with: "
            "pip install 'offline-ai-file-organizer[gui]'"
        ) from exc

    import sys
    app_path = str(Path(__file__).with_name("web_app.py"))
    sys.argv = [
        "streamlit", "run", app_path,
        "--server.address=127.0.0.1",
        "--server.headless=false",
        "--browser.gatherUsageStats=false",
    ]
    stcli.main()


if __name__ == "__main__":
    main()
