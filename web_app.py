"""Local-first Streamlit dashboard: choose, preview, approve, and undo."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from file_organizer import FileOrganizer, PROVIDER_DEFAULTS, load_config
from smart_organizer import Taxonomy
from ui_helpers import manual_review_action, preflight_review, review_rows, select_reviewed_actions


def render():
    import streamlit as st

    st.set_page_config(page_title="Offline AI File Organizer", page_icon="📂", layout="wide")
    st.title("📂 Smart File Organizer")
    st.caption("Choose a folder → Choose organization → Review → Apply or undo")
    st.info(
        "Review-first: documents are not moved until you approve. "
        "Local models can keep content on your computer; cloud models send "
        "file previews to their provider.", icon="🔒",
    )

    cfg = copy.deepcopy(load_config())
    st.session_state.setdefault("review_actions", [])
    st.session_state.setdefault("review_rows", [])
    st.session_state.setdefault("review_root", None)
    st.session_state.setdefault("review_serial", 0)
    st.session_state.setdefault("watch_controller", None)

    st.subheader("1. Choose your folder")
    folder = st.text_input(
        "Folder to organize", value=str(Path.home() / "Downloads"),
        help="Use a copy of important files to try the organizer first.",
    )
    folder_path = Path(folder).expanduser().resolve(strict=False)
    valid_folder = folder_path.is_dir()
    if not valid_folder:
        st.warning("Select an existing folder before running analysis.")

    st.subheader("2. Choose your folder layout")
    col_profile, col_description = st.columns([2, 1])
    with col_profile:
        profile = st.radio(
            "Organization profile", ["Smart", "Simple", "Custom"], horizontal=True,
            help="Smart creates approved two-level categories; Simple uses one level.",
        )
    with col_description:
        st.caption("Maximum two category levels in Smart mode. "
                   "The AI cannot invent new folder names.")
    cfg["organizer"]["profile"] = profile.lower()

    if profile == "Custom":
        with st.expander("Custom categories and approved subfolders"):
            roots = st.text_input(
                "Top-level categories (comma-separated)",
                value=", ".join(cfg["organizer"].get("categories", [])),
            )
            cfg["organizer"]["categories"] = [x.strip() for x in roots.split(",") if x.strip()]
            custom = st.text_area(
                'Subcategories in JSON (e.g. {"Finance":["Invoices","Receipts"]})',
                value=json.dumps(cfg["organizer"].get("smart_subcategories", {}), indent=2),
                height=160,
            )
            try:
                cfg["organizer"]["smart_subcategories"] = json.loads(custom)
            except json.JSONDecodeError:
                st.warning("Custom subcategories must be valid JSON.")
    elif profile == "Smart":
        with st.expander("See approved Smart folders"):
            st.json(cfg["organizer"].get("smart_subcategories", {}))

    with st.sidebar:
        st.header("AI and preferences")
        with st.expander("Model settings", expanded=True):
            providers = list(PROVIDER_DEFAULTS)
            default_provider = cfg["llm"].get("provider", "lm_studio")
            provider = st.selectbox(
                "AI provider", providers,
                index=providers.index(default_provider) if default_provider in providers else 0,
            )
            model = st.text_input("Model", value=str(cfg["llm"].get("model", "auto")))
            endpoint = st.text_input("Endpoint override", value=str(cfg["llm"].get("base_url", "")))
            api_key = st.text_input("API key (not saved)", type="password")
        with st.expander("Advanced controls"):
            rename = st.checkbox("Rename files", value=True)
            organize = st.checkbox("Organize into folders", value=True)
            images = st.checkbox(
                "Include images", value=bool(cfg["organizer"].get("enable_images", False))
            )
            deduplicate = st.checkbox(
                "Flag duplicate content", value=bool(cfg["organizer"].get("detect_duplicates", True))
            )
            naming = st.text_input(
                "Filename template",
                value=cfg["organizer"].get("naming_template", "{title} ({date})"),
                help="Allowed placeholders: {title}, {date} and {category}.",
            )
        st.caption("Cloud models transmit the selected file's preview to the provider.")

    cfg["llm"].update({"provider": provider, "model": model, "base_url": endpoint, "api_key": api_key})
    cfg["organizer"].update({
        "enable_images": images, "detect_duplicates": deduplicate,
        "naming_template": naming,
    })

    def make_organizer():
        Taxonomy(
            cfg["organizer"]["categories"], cfg["organizer"]["profile"],
            cfg["organizer"].get("smart_subcategories"),
        )
        return FileOrganizer(str(folder_path), config=cfg)

    tab_review, tab_watch, tab_queue, tab_rules, tab_history = st.tabs(
        ["Review files", "Watch folder", "Needs Review", "Sorting rules", "Undo history"]
    )
    with tab_review:
        st.subheader("3. Preview AI suggestions")
        st.write("Analysis creates suggestions; it doesn't move any file.")
        if st.button(
            "Analyze and preview", type="primary",
            disabled=not valid_folder or not (rename or organize),
        ):
            try:
                organizer = make_organizer()
                ok, message = organizer.llm.test_connection()
                if not ok:
                    st.warning(f"AI unavailable: {message}. Matching saved rules still work.")
                with st.spinner("Building a safe review plan…"):
                    actions = organizer.build_plan(rename=rename, organize=organize)
                st.session_state.review_actions = actions
                st.session_state.review_rows = review_rows(actions)
                st.session_state.review_root = str(folder_path)
                st.session_state.review_serial += 1
                st.success(
                    f"{len(actions)} proposal(s); "
                    f"{len(organizer.review_queue.items())} item(s) need attention."
                )
            except Exception as exc:
                st.error(f"Analysis failed: {exc}")

        originals = st.session_state.review_actions
        if originals and st.session_state.review_root != str(folder_path):
            st.warning("This review belongs to a different folder. Select its original folder.")
        elif originals:
            st.write(f"**{len(originals)} suggestions**. Uncheck Apply to skip a file.")
            edited = st.data_editor(
                st.session_state.review_rows,
                key=f"review_{st.session_state.review_serial}",
                hide_index=True, use_container_width=True, num_rows="fixed",
                disabled=["Original", "Why", "Source"],
            )
            try:
                organizer = make_organizer()
                approved = select_reviewed_actions(organizer, originals, edited)
                st.caption(f"{len(approved)} / {len(originals)} selected")
                with st.expander("Inspect exact before/after paths"):
                    st.json([{"from": a["old_path"], "to": a["new_path"]} for a in approved])
                if st.button("Validate and save plan", disabled=not approved):
                    preflight_review(organizer, approved)
                    name = f"review_plan_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
                    saved = organizer.save_plan(str(folder_path / name))
                    st.success(f"Saved plan: {saved}")

                st.subheader("4. Apply reviewed changes")
                confirm = st.checkbox(
                    "I have reviewed the destinations and authorize these changes.",
                    key="approve_plan_changes",
                )
                if st.button("Apply selected changes", type="primary",
                             disabled=not (confirm and approved)):
                    preflight_review(organizer, approved)
                    log = organizer.apply_plan(save_log=True)
                    moved = len(organizer.executed_log)
                    st.session_state.review_actions = []
                    st.session_state.review_rows = []
                    st.success(f"{moved} file(s) moved; undo is available from the history tab.")
                    if log:
                        st.code(str(log), language=None)
            except Exception as exc:
                st.error(f"Review validation blocked an unsafe change: {exc}")
        else:
            st.caption("No plan yet. Click Analyze and preview.")

    with tab_watch:
        st.subheader("Monitor newly arriving files")
        st.caption("Default is review-only. Automatic changes require explicit authorization.")
        workers = st.number_input("Parallel workers", min_value=1, max_value=16, value=2)
        delay = st.number_input(
            "File stability delay (seconds)", min_value=0.5, max_value=60.0,
            value=1.5, step=0.5,
        )
        auto = st.checkbox("Apply suggestions unattended (advanced)", value=False)
        authorize = st.checkbox("I authorize unattended file moves", disabled=not auto)
        running = st.session_state.watch_controller

        if running is None:
            if st.button(
                "Start monitoring",
                disabled=not valid_folder or not (rename or organize) or (auto and not authorize),
            ):
                try:
                    from ui_watch import WatchController
                    organizer = make_organizer()
                    controller = WatchController(
                        organizer, rename=rename, organize=organize,
                        workers=int(workers), stability_seconds=float(delay), auto_apply=auto,
                    )
                    controller.start()
                    st.session_state.watch_controller = controller
                    st.success("Monitoring started.")
                except Exception as exc:
                    st.error(f"Cannot start watcher: {exc}")
        else:
            st.write(f"Watching **{running.service.root}**")
            st.json(running.stats())
            if st.button("Stop monitoring and save results"):
                try:
                    result = running.stop()
                    st.session_state.watch_controller = None
                    st.success("Watcher stopped and results saved.")
                    st.json({
                        "plan": str(result["plan_path"]) if result["plan_path"] else None,
                        "undo_log": str(result["log_path"]) if result["log_path"] else None,
                    })
                except Exception as exc:
                    st.error(f"Cannot stop watcher: {exc}")

    with tab_queue:
        st.subheader("Files needing review")
        st.caption("Identical files and uncertain classifications are left untouched.")
        if valid_folder:
            try:
                organizer = make_organizer()
                items = organizer.review_queue.items()
                st.write(f"**{len(items)} item(s)**")
                if items:
                    st.dataframe(items, hide_index=True, use_container_width=True)
                    selected = st.selectbox(
                        "File to review", [item["path"] for item in items]
                    )
                    queued = next(item for item in items if item["path"] == selected)
                    st.caption(f"Reason: {queued.get('reason', 'Unknown')}")
                    st.write("**Resolve manually** — approve a name and folder without AI")
                    filename = st.text_input("Reviewed filename", value=Path(selected).name)
                    chosen_root = st.selectbox("Move into category", organizer.categories)
                    chosen_sub = st.selectbox(
                        "Approved subfolder",
                        [""] + organizer.taxonomy.subcategories.get(chosen_root, []),
                    )
                    remember = st.checkbox(
                        "Remember this classification as a rule (optional)"
                    )
                    pattern = st.text_input(
                        "Matching filename pattern for future files",
                        value=Path(selected).name, disabled=not remember,
                        help="Use a narrow pattern to avoid sorting unrelated documents.",
                    )
                    authorized = st.checkbox(
                        "I reviewed this file and approve moving it to this folder."
                    )
                    if st.button("Move reviewed file", disabled=not authorized):
                        action = manual_review_action(
                            organizer, queued, filename, chosen_root, chosen_sub
                        )
                        organizer.planned_actions = [action]
                        log = organizer.apply_plan(save_log=True)
                        if len(organizer.executed_log) == 1:
                            organizer.review_queue.dismiss(selected)
                            if remember:
                                organizer.rulebook.add({
                                    "pattern": pattern,
                                    "category": chosen_root,
                                    "subcategory": chosen_sub,
                                })
                            st.success(f"Moved safely. Undo log: {log}")
                        else:
                            st.error("The file was not moved; check for a destination conflict.")
                    if st.button("Dismiss from queue without moving"):
                        organizer.review_queue.dismiss(selected)
                        st.success("Dismissed. Original file was not changed.")
                else:
                    st.info("No pending review items.")
            except Exception as exc:
                st.error(f"Cannot load queue: {exc}")

    with tab_rules:
        st.subheader("Reusable rules save AI calls")
        st.write("Match a filename and route it without sending content to an AI model.")
        if valid_folder:
            try:
                organizer = make_organizer()
                with st.expander("Existing rules"):
                    st.json(organizer.rulebook.list_rules())
                pattern = st.text_input("Filename pattern", value="*invoice*.pdf")
                left, right = st.columns(2)
                with left:
                    root = st.selectbox("Category", organizer.categories)
                with right:
                    sub = st.selectbox(
                        "Subcategory", [""] + organizer.taxonomy.subcategories.get(root, [])
                    )
                contains = st.text_input("Text that must be present (optional)")
                if st.button("Save sorting rule"):
                    organizer.rulebook.add({
                        "pattern": pattern, "category": root, "subcategory": sub,
                        "contains": contains,
                    })
                    st.success("Rule saved in the folder's .organizer/rules.json.")
            except Exception as exc:
                st.error(f"Cannot manage rules: {exc}")

    with tab_history:
        st.subheader("Undo previous changes")
        if valid_folder:
            logs = sorted(folder_path.glob("organization_log_*.json"), reverse=True)[:50]
            if not logs:
                st.info("No undo logs found.")
            else:
                selected_log = st.selectbox("Execution log", [str(p) for p in logs])
                try:
                    data = json.loads(Path(selected_log).read_text(encoding="utf-8"))
                    st.write(f"Recorded moves: {len(data.get('actions', []))}")
                except Exception:
                    st.warning("Cannot read selected log.")
                confirm = st.checkbox(
                    "Restore only unchanged files with free original paths."
                )
                if st.button("Undo selected run", disabled=not confirm):
                    restored = FileOrganizer.undo_from_log(selected_log)
                    st.success(f"{restored} file(s) restored.")


if __name__ == "__main__":
    render()
