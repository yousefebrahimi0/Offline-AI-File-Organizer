# 🤖 Offline AI File Organizer
> *I kept telling myself I'd organize my files "later." Days passed. Thousands of cryptic filenames piled up. I checked and reviewed some apps on Windows to rename and organize my files, but none of them were good enough. So one day I realized: why force discipline when I can automate intelligence using local LLMs? So I built this.*

![Offline AI File Organizer Banner](banner.png)

**Transform your messy file system into an organized masterpiece using any local or cloud LLM.**

Automatically rename and organize your documents (and optionally images) using AI that runs entirely on your machine—or connect any OpenAI-compatible, Anthropic, or Gemini model you prefer.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/License-Apache%202.0-green.svg" alt="License">
  <img src="https://img.shields.io/badge/AI-Any%20Local%20or%20Cloud%20LLM-purple.svg" alt="Universal LLM">
</p>

---

## 🆕 Updates

### v2.3 — Local Web UI and Installable Package
- **Optional Streamlit dashboard**: locally review, edit, approve and undo suggested changes without using the CLI.
- **Live monitor controls**: start and stop review-only or explicitly authorized automatic watch sessions in the browser.
- **Installable Python package**: command-line and local GUI launchers, optional OCR/UI dependencies, wheel and source distributions.
- **Cross-platform CI**: Windows, macOS and Linux across multiple supported Python versions.

### v2.1 — Safer File Operations
- **Versioned plans**: New plans store source size, modification time and SHA-256 fingerprints and must match the selected root folder.
- **No-overwrite execution**: Applying a plan preflights every action and refuses existing destinations, changed sources, symbolic links and paths outside the selected folder.
- **Safer undo**: Undo refuses to overwrite recreated originals and skips files changed after organization. Keep the log in its original organization root folder.
- **AI failure handling**: Files are skipped when the model fails or returns incomplete JSON instead of being filed under `Miscellaneous`.
- **Plan compatibility**: Version 2 saved plans must be regenerated; version 2 organization logs can still be used for undo if kept in their original root folder.

### v2.2 — Watch-Folder Mode & Parallel Analysis
- **Watch folders**: Monitor a folder recursively for new or modified supported files with `watchdog`. Files must remain stable before analysis begins, so incomplete copies are not processed.
- **Parallel analysis**: Configure a bounded worker pool for concurrent extraction and LLM requests. File moves are serialized to prevent destination collisions.
- **Review-first by default**: Watch mode saves a version 3 approval plan and does not move files unless `--auto-apply` is explicitly supplied. Automatic moves are recorded in a standard undo log.

### v2.0 — Universal LLM Support, Plan Caching, Undo, & Expanded Formats
- **Universal LLM Provider Layer**: No longer locked to LM Studio + Mistral-7B. Connect **LM Studio**, **Ollama**, **llama.cpp**, **OpenAI**, **OpenRouter**, **Anthropic**, **Gemini**, or any custom OpenAI-compatible endpoint via `config.yaml` or CLI flags, with automatic local model detection (`model: "auto"`).
- **Cached Dry-Run Plans & One-Click Undo**: Dry-run results are now cached so live mode applies the exact approved changes without calling the LLM twice. Added `--save-plan`, `--apply-plan`, and `--undo <log.json>` to safely reverse any batch.
- **Expanded Format & Image Support**: Added built-in extractors for `.rtf`, `.odt`, and `.pptx`, migrated PDF parsing from deprecated `PyPDF2` to `pypdf` (with `None`-safe handling for scanned PDFs), and added optional image organization (`--include-images`) via Vision-Language Models (VLMs) or `pytesseract` OCR.
- **Reliability & Security Fixes**: Automatically excludes `Organized/` and ignored folders from recursive scans, sanitizes AI-generated categories against an allowed list to prevent invalid paths, and combines naming + categorization into a single structured JSON prompt.
- **Automated Testing (CI)**: Added a `pytest` unit test suite and GitHub Actions workflow.

---

## ✨ Features

### 🎯 Intelligent Renaming
- **AI-Powered Analysis**: Reads actual file content to generate meaningful names
- **Smart Naming**: Transforms `8a095-4d0f6a90008b.pdf` → `My personal test on NY project (2025-03).pdf`
- **Date Integration**: Automatically adds modification date (`YYYY-MM`) to filenames
- **Duplicate Handling**: Safely manages duplicate names with incremental suffixes
- **Multilingual**: Supports both English and Persian content

### 📁 Smart Organization
- **Content-Based Categorization**: AI analyzes documents and sorts them into relevant folders
- **Customizable Categories**: Edit your folder taxonomy directly in `config.yaml`
- **Ignore Rules**: Automatically skips `Organized/`, `.git/`, `node_modules/`, and virtual environments
- **Recursive Processing**: Handles nested folders and subdirectories

### 🔌 Universal LLM Support (Privacy-First)
- **100% Offline by Default**: Works out of the box with **LM Studio**, **Ollama**, or **llama.cpp**
- **Bring Your Own Model**: Switch to any local model (`auto`-detected) or cloud API (**OpenAI**, **OpenRouter**, **Anthropic**, **Gemini**) in `config.yaml` or via CLI flags

### 🛡️ Safety Features
- **Exact Dry-Run Plan Caching**: Live mode executes the exact plan you reviewed, after validating the source files
- **Save & Replay Plans**: Export a dry-run plan with `--save-plan plan.json` and apply later with `--apply-plan plan.json`
- **One-Click Undo**: Reverse a run with `python file_organizer.py --undo <organization_log.json>`; existing files and post-run modifications are protected
- **Non-Destructive**: Original files are moved/renamed, never deleted

---

## 📋 Supported File Types

- **Documents**: PDF, DOCX, TXT, MD, RTF, ODT, PPTX
- **Spreadsheets**: CSV, XLSX, XLS
- **E-books**: EPUB
- **Images (Optional)**: PNG, JPG, JPEG, WEBP (enable via `config.yaml` or `--include-images` using a Vision LLM or `pytesseract` OCR)

---

## 🖥️ Local web interface and package installation

Install directly from this repository (no PyPI release required):

```bash
python -m pip install -e ".[gui]"
offline-ai-organizer-gui
```

The GUI launches Streamlit on **127.0.0.1** (not a public server). It includes model settings, review/edit/skip proposals, checked application, watch controls and undo history. Cloud providers transmit file content to the selected provider; choose LM Studio or Ollama if you want local processing. API keys in GUI are not written to a plan/log.

For the CLI-only installation:

```bash
python -m pip install -e .
offline-ai-organizer --help
```

Optional image OCR requires `python -m pip install -e ".[ocr]"` plus a separately installed Tesseract executable. Run the web interface on a trusted local machine only; do not expose its port on your network or the internet.

## 🚀 Quick Start

### Prerequisites
1. **Python 3.9+** - [Download here](https://www.python.org/downloads/)
2. A local LLM runner such as **LM Studio** ([lmstudio.ai](https://lmstudio.ai/)) or **Ollama** ([ollama.com](https://ollama.com/)), **or** an API key for OpenAI / OpenRouter / Anthropic / Gemini.

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yousefebrahimi0/Offline-AI-File-Organizer.git
   cd Offline-AI-File-Organizer
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
![Screenshot One](screenshot1.png)

3. **Configure your LLM (`config.yaml`)**
   - For **LM Studio**: Start the local server (port `1234`) with any loaded model. `config.yaml` defaults to `provider: "lm_studio"` and `model: "auto"`.
   - For **Ollama**: Set `provider: "ollama"` in `config.yaml` (or pass `--provider ollama`).
   - For **Cloud / Custom APIs**: Set `provider` and `model` in `config.yaml` and export your API key (e.g., `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `LLM_API_KEY`).

![Screenshot Two](screenshot2.png)

### Usage

#### Watch-folder mode
```bash
# Analyse new or changed files in parallel and save an approval plan.
# Files are not moved until you review and apply the plan.
python file_organizer.py --folder "./Downloads" --watch --rename --organize --workers 3

# Explicitly opt in to automatic moving; every successful move is logged for undo.
python file_organizer.py --folder "./Downloads" --watch --rename --organize --workers 3 --auto-apply
```

Stop the watcher with Ctrl+C. In review-only mode, a `watch_plan_*.json` file is written to the watched folder and can be applied later with `--apply-plan`. Automatic mode writes an `organization_log_watch_*.json` undo log.

The stability delay defaults to 1.5 seconds and can be changed with `--stability-delay`. The worker count defaults to 2 and can be changed with `--workers`.

#### Interactive Mode
```bash
python file_organizer.py
```

#### CLI Examples
```bash
# Organize with local Ollama (auto-detects loaded model)
python file_organizer.py --folder "./Downloads" --provider ollama --rename --organize

# Include images using a local or cloud Vision model
python file_organizer.py --folder "./Receipts" --provider ollama --model qwen2.5-vl --include-images --rename --organize

# Save a dry-run plan to review, then apply it later
python file_organizer.py --folder "./Docs" --rename --organize --save-plan plan.json
python file_organizer.py --apply-plan plan.json

# Undo a previous run
python file_organizer.py --undo "./Downloads/organization_log_20261123_153000.json"
```

---

## ⚙️ Configuration (`config.yaml`)

```yaml
llm:
  provider: "lm_studio"   # lm_studio, ollama, llama_cpp, openai, openrouter, anthropic, gemini, openai_compatible
  base_url: ""            # Optional custom endpoint
  model: "auto"           # Auto-detect local model, or specify any model name
  api_key: ""             # Prefer environment variables for cloud keys
  temperature: 0.2
  max_tokens: 120
  timeout: 45

organizer:
  max_content_length: 3000
  organize_folder_name: "Organized"
  enable_images: false
  use_vision_model: true
  ignore_folders: ["Organized", ".git", "__pycache__", "node_modules", ".venv", "venv"]
  categories: ["Work", "Personal", "Finance", "Medical", "Education", "Legal", "Photos", "Projects", "Archive", "Miscellaneous"]
```

---

## 🧪 Running Tests

```bash
pip install pytest
python -m pytest -v
```

---

## 📝 License & Attribution
Licensed under the [Apache License 2.0](LICENSE).

If you use this project in your work, software, or research, please include the attribution in the [NOTICE](NOTICE) file and credit:
> Yousef Ebrahimi — https://github.com/yousefebrahimi0/Offline-AI-File-Organizer

---

<p align="center">Made for everyone tired of messy file systems</p>

<p align="center">
  <sub>⭐ Star this repo if it helped you organize your files!</sub>
</p>
