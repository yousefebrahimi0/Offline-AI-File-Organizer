"""Local-only browser UI. Launch using 'offline-ai-organizer-gui'."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from file_organizer import FileOrganizer, PROVIDER_DEFAULTS, load_config
from ui_helpers import preflight_review, review_rows, select_reviewed_actions


def render():
    import streamlit as st

    st.set_page_config(page_title="Offline AI File Organizer", page_icon="📂", layout="wide")
    st.title("📂 Offline AI File Organizer")
    st.caption("Private by default · Review changes before applying · Local-only server")
    st.info(
        "This app runs locally. Selecting a cloud provider sends the analysed content "
        "to that provider. API keys entered below are not stored in plans or logs.",
        icon="🔒",
    )

    cfg = copy.deepcopy(load_config())
    with st.sidebar:
        st.header("Workspace")
        folder = st.text_input("Folder to organize", value=str(Path.home() / "Downloads"))
        folder_path = Path(folder).expanduser().resolve(strict=False)
        valid_folder = folder_path.is_dir()
        if not valid_folder:
            st.warning("Choose an existing local folder.")

        st.header("Model")
        providers = list(PROVIDER_DEFAULTS)
        configured_provider = cfg["llm"].get("provider", "lm_studio")
        provider = st.selectbox(
            "Provider", providers,
            index=providers.index(configured_provider) if configured_provider in providers else 0,
        )
        model = st.text_input("Model (auto for local endpoints)", value=str(cfg["llm"]["model"]))
        endpoint = st.text_input("Custom endpoint (optional)", value=str(cfg["llm"].get("base_url", "")))
        api_key = st.text_input("API key (optional; prefer environment)", type="password")
        st.header("Options")
        rename = st.checkbox("Rename files", value=True)
        organize = st.checkbox("Organize by category", value=True)
        include_images = st.checkbox("Include images", value=bool(cfg["organizer"]["enable_images"]))

    cfg["llm"].update({
        "provider": provider, "model": model, "base_url": endpoint, "api_key": api_key,
    })
    cfg["organizer"]["enable_images"] = include_images

    st.session_state.setdefault("review_actions", [])
    st.session_state.setdefault("review_root", None)
    st.session_state.setdefault("review_rows", [])
    st.session_state.setdefault("last_log", None)
    st.session_state.setdefault("watch_controller", None)

    def make_organizer():
        return FileOrganizer(str(folder_path), config=cfg)

    tab_review, tab_watch, tab_history = st.tabs(["Review & apply", "Watch folder", "History / undo"])

    with tab_review:
        st.subheader("AI analysis")
        st.write("Analyze documents to create a proposed plan. Nothing is moved during this step.")
        if st.button("Analyze folder", type="primary", disabled=not valid_folder or not (rename or organize)):
            try:
                organizer = make_organizer()
                ok, message = organizer.llm.test_connection()
                if not ok:
                    st.error(message)
                else:
                    with st.spinner("Analysing files…"):
                        actions = organizer.build_plan(rename=rename, organize=organize)
                    st.session_state.review_actions = actions
                    st.session_state.review_rows = review_rows(actions)
                    st.session_state.review_root = str(folder_path)
                    st.success(f"Created {len(actions)} proposals using {message}.")
            except Exception as exc:
                st.error(f"Analysis failed: {exc}")

        original = st.session_state.review_actions
        if original:
            if st.session_state.review_root != str(folder_path):
                st.warning("This review belongs to a different folder. Select its original folder to continue.")
            else:
                st.caption(f"{len(original)} proposed file operations. Disable Apply to skip a row.")
                table = st.data_editor(
                    st.session_state.review_rows,
                    hide_index=True,
                    use_container_width=True,
                    num_rows="fixed",
                    disabled=["Original"],
                    key="review_editor",
                )
                st.session_state.review_rows = table
                try:
                    organizer = make_organizer()
                    approved = select_reviewed_actions(organizer, original, table)
                    st.write(f"**Selected:** {len(approved)} / {len(original)}")
                    with st.expander("Inspect exact paths"):
                        st.json([{"from": a["old_path"], "to": a["new_path"]} for a in approved])

                    if st.button("Validate and save approved plan", disabled=not approved):
                        preflight_review(organizer, approved)
                        name = f"review_plan_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
                        plan_path = folder_path / name
                        organizer.save_plan(str(plan_path))
                        st.success(f"Saved for later: {plan_path}")

                    confirmed = st.checkbox(
                        "I have reviewed the selected destinations and authorize these moves.",
                        value=False, key="approve_moves",
                    )
                    if st.button(
                        "Apply approved changes", type="primary",
                        disabled=not (confirmed and approved),
                    ):
                        preflight_review(organizer, approved)
                        with st.spinner("Applying approved changes…"):
                            log = organizer.apply_plan(save_log=True)
                        st.session_state.last_log = str(log) if log else None
                        st.session_state.review_actions = []
                        st.session_state.review_rows = []
                        st.success(f"Applied {len(organizer.executed_log)} moves.")
                        if log:
                            st.code(str(log), language=None)
                except Exception as exc:
                    st.error(f"Review validation failed: {exc}")

    with tab_watch:
        st.subheader("Live folder monitoring")
        st.write(
            "Watch mode monitors new or modified files. The default is review-only: "
            "new suggestions are stored in a JSON plan; automatic moving is opt-in."
        )
        workers = st.number_input("Parallel analysis workers", min_value=1, max_value=16, value=2)
        delay = st.number_input("File stability delay (seconds)", min_value=0.5, max_value=60.0, value=1.5, step=0.5)
        auto_apply = st.checkbox("Automatically move files (requires explicit approval)", value=False)
        authorize_watch = st.checkbox(
            "I authorize unattended file moves in this folder.",
            disabled=not auto_apply,
        )
        running = st.session_state.watch_controller
        if running is None:
            if st.button(
                "Start monitoring", disabled=not valid_folder or
                (auto_apply and not authorize_watch) or not (rename or organize),
            ):
                try:
                    from ui_watch import WatchController
                    organizer = make_organizer()
                    ok, message = organizer.llm.test_connection()
                    if not ok:
                        st.error(message)
                    else:
                        controller = WatchController(
                            organizer, rename=rename, organize=organize,
                            workers=int(workers), stability_seconds=float(delay),
                            auto_apply=auto_apply,
                        )
                        controller.start()
                        st.session_state.watch_controller = controller
                        st.success(f"Monitoring started: {folder_path}")
                except Exception as exc:
                    st.error(f"Cannot start watcher: {exc}")
        else:
            st.write(f"Monitoring **{running.service.root}**")
            st.json(running.stats())
            if st.button("Stop monitoring and save results"):
                try:
                    result = running.stop()
                    st.session_state.watch_controller = None
                    st.success("Watcher stopped and results saved.")
                    st.json({
                        "statistics": result["stats"],
                        "plan": str(result["plan_path"]) if result["plan_path"] else None,
                        "undo_log": str(result["log_path"]) if result["log_path"] else None,
                    })
                except Exception as exc:
                    st.error(f"Stopping watcher failed: {exc}")
            st.caption("Click Stop to flush the final plan and undo log before closing the browser.")

    with tab_history:
        st.subheader("Saved operations")
        if valid_folder:
            logs = sorted(folder_path.glob("organization_log_*.json"), reverse=True)[:50]
            if logs:
                options = [str(p) for p in logs]
                selected_log = st.selectbox("Choose an undo log", options)
                if selected_log:
                    try:
                        data = json.loads(Path(selected_log).read_text(encoding="utf-8"))
                        st.write(f"Logged moves: {len(data.get('actions', []))}")
                    except (OSError, json.JSONDecodeError, TypeError):
                        st.warning("Cannot read this log.")
                    confirm_undo = st.checkbox(
                        "I understand undo will restore only unchanged files with free original paths."
                    )
                    if st.button("Undo selected log", disabled=not confirm_undo):
                        restored = FileOrganizer.undo_from_log(selected_log)
                        st.success(f"Restored {restored} file(s). Check the console for skipped conflicts.")
            else:
                st.info("No organization logs found in this folder.")
        st.caption("Undo never deliberately replaces an existing original file.")


if __name__ == "__main__":
    render()
