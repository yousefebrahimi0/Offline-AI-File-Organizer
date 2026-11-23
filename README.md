# 🤖 Offline AI File Organizer

**Organize messy folders with AI—without giving up control of your files.**

Rename and categorize documents based on their contents using **local or cloud LLMs**. Review suggestions before moving anything, monitor folders for new files, and undo previous moves. Available as a **local web dashboard** and a **command-line tool** for Windows, macOS, and Linux.

![Offline AI File Organizer](banner.png)

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)
![Local or cloud LLM](https://img.shields.io/badge/AI-Local%20or%20cloud-purple)

> **Privacy:** With LM Studio, Ollama, or llama.cpp running locally, AI processing can stay on your computer. **Cloud models are optional, but choosing them sends analyzed file content to the configured provider.** The interface itself runs on localhost; this does not make a remote model private.

## What you can do

| Feature | User benefit |
| --- | --- |
| **Smart renaming** | Turn cryptic filenames into readable names based on file content and modification month. |
| **Simple categorization** | Route files to configurable category folders under one \`Organized/\` directory. |
| **Review and approval** | Inspect, rename, re-categorize, or skip suggestions before applying them. |
| **Watch-folder mode** | Analyse newly arriving files after they finish copying. Automatic moves are opt-in. |
| **Parallel analysis** | Analyse several files concurrently using a configurable number of workers. |
| **Undo and safety checks** | Saved plans, SHA-256 fingerprint verification, no-overwrite moves, and undo logs. |
| **Choice of AI** | LM Studio, Ollama, llama.cpp, OpenAI, OpenRouter, Anthropic, Gemini, or compatible endpoints. |
| **Local browser or CLI** | Use an interactive dashboard or automate tasks from a terminal. |

## Example: Before and after

\`\`\`text
Before
Downloads/
├── a8d137cc.pdf
├── document_final_3.docx
└── receipt_019.jpg

After (illustrative — depends on the AI model)
Downloads/
└── Organized/
    ├── Finance/
    │   └── Electricity Invoice (2026-11).pdf
    ├── Projects/
    │   └── Project Planning Notes (2026-11).docx
    └── Photos/
        └── Shop Receipt (2026-11).jpg
\`\`\`

The example uses optional image analysis. Categories and filenames are AI suggestions, not guaranteed classifications.

## Get started in three steps

**Requirements:** Python 3.9+ and either a local AI server such as [LM Studio](https://lmstudio.ai/) / [Ollama](https://ollama.com/), or API credentials for a supported cloud provider.

### 1. Install from the repository

\`\`\`bash
git clone https://github.com/yousefebrahimi0/Offline-AI-File-Organizer.git
cd Offline-AI-File-Organizer
python -m pip install -e ".[gui]"
\`\`\`

This installs the application and its optional Streamlit interface. It does **not** create a standalone Windows EXE or macOS APP.

### 2. Open the local web dashboard

\`\`\`bash
offline-ai-organizer-gui
\`\`\`

The app opens in a browser at **http://127.0.0.1:8501** by default, bound to your own computer.

Select a folder, choose your AI provider/model, and click **Analyze folder**. With the default config, LM Studio is expected at \`http://localhost:1234/v1\`; to use Ollama, change the provider to \`ollama\` and run its local model server.

### 3. Review → approve → apply

The app first builds suggestions **without moving files**. Review the proposed names and categories, edit anything you dislike, and uncheck files you want to leave untouched. Moving files requires explicit approval. Successfully moved files are recorded in an undo log.

The dashboard also includes **Watch folder** and **History / undo** tabs.

> Start with a folder of **copied test files**, especially before enabling automatic watch-folder moves.

## How categorization works today

The organizer **recursively scans existing input subfolders**, but its **generated output taxonomy is flat**: a single category level under \`Organized/\`.

\`\`\`text
Selected folder/
└── Organized/
    ├── Work/
    ├── Personal/
    ├── Finance/
    ├── Medical/
    ├── Education/
    ├── Legal/
    ├── Photos/
    ├── Projects/
    ├── Archive/
    └── Miscellaneous/
\`\`\`

Only categories receiving files are created. These names can be customized in \`config.yaml\`. The app does **not yet** create nested structures such as \`Finance/Invoices/2026\` or invent unlimited new folders.

The AI returns one suggested category from the configured list. Unrecognized category names may fall back to \`Miscellaneous\`; this is **not a calibrated confidence score**.

## Local and cloud AI providers

| Provider | Default use | Where content goes |
| --- | --- | --- |
| LM Studio | Local OpenAI-compatible server | Stays local when configured locally |
| Ollama | Local model server | Stays local when configured locally |
| llama.cpp | Local OpenAI-compatible server | Stays local when configured locally |
| OpenAI / OpenRouter | Cloud API with key | Sent to cloud provider |
| Anthropic / Gemini | Cloud API with key | Sent to cloud provider |
| Custom OpenAI-compatible | User-supplied endpoint | Depends on endpoint |

Configure providers in the dashboard, \`config.yaml\`, or CLI flags. Prefer environment variables (for example \`OPENAI_API_KEY\`) for cloud credentials; GUI-entered API keys are not saved in organization plans/logs.

## CLI usage

Install without the web interface:

\`\`\`bash
python -m pip install -e .
offline-ai-organizer --help
\`\`\`

**Save and apply an approved plan**

\`\`\`bash
offline-ai-organizer --folder "./Downloads" --provider ollama --rename --organize --save-plan plan.json
offline-ai-organizer --apply-plan plan.json
\`\`\`

**Watch for new files (review-only by default)**

\`\`\`bash
offline-ai-organizer --folder "./Downloads" --watch --rename --organize --workers 3
\`\`\`

**Explicitly allow automatic moves**

\`\`\`bash
offline-ai-organizer --folder "./Downloads" --watch --rename --organize --workers 3 --auto-apply
\`\`\`

Use \`--stability-delay 3\` to require three seconds of unchanged size and modification time before analysis. Watch mode handles new file events; it does not bulk-scan all existing files at startup. Stop with **Ctrl+C**.

**Undo**

\`\`\`bash
offline-ai-organizer --undo "./Downloads/organization_log_YYYYMMDD_HHMMSS.json"
\`\`\`

Undo skips files that changed after a move and refuses to overwrite a file that now occupies the original path. Version 2 plans need regeneration; saved version 3 plans include source fingerprints.

## Supported files

| Type | Extensions | Important notes |
| --- | --- | --- |
| Documents | PDF, DOCX, TXT, MD, RTF, ODT, PPTX | Extraction quality depends on format. PDF reads an initial text preview. |
| Spreadsheets | CSV, XLSX, XLS | Legacy XLS may additionally require \`xlrd\`. |
| E-books | EPUB | Metadata extraction, not full-book semantic indexing. |
| Images (optional) | PNG, JPG, JPEG, WEBP | Vision LLM support or optional Tesseract OCR. |

Image analysis is disabled by default. Enable it in \`config.yaml\` or with \`--include-images\`. Optional OCR dependencies:

\`\`\`bash
python -m pip install -e ".[ocr]"
\`\`\`

Tesseract itself must be installed separately. **Scanned PDF OCR is not yet built in.** Audio/video analysis and semantic search are also not implemented.

## Configuration

Edit [config.yaml](config.yaml) to select your LLM, adjust ignored folders, configure categories, and set watcher defaults. For example:

\`\`\`yaml
llm:
  provider: "lm_studio"
  model: "auto"
  base_url: ""
  api_key: ""

organizer:
  organize_folder_name: "Organized"
  enable_images: false
  watch_workers: 2
  watch_stability_seconds: 1.5
  categories: [Work, Personal, Finance, Medical, Education, Legal, Photos, Projects, Archive, Miscellaneous]
\`\`\`

## Safety and limitations

- **Review first:** Regular GUI analysis and default watch mode create proposals rather than moving files automatically.
- **No target overwrite:** Source fingerprints, root-bound plans, and collision checks protect against many accidental changes.
- **Undo is conditional:** Files must remain unchanged and their previous locations must be available.
- **Not a single transaction:** A batch can partially succeed if later moves fail; consult the execution log.
- **AI can be wrong:** Review sensitive documents and category suggestions before applying changes.
- **Local app ≠ local inference:** Remote cloud models can receive the file content analyzed by the program.
- **Not yet a full file manager:** No arbitrary nested categories, content-based deduplication, semantic search, or standalone desktop installers.

## What could come next?

These are **ideas, not current features**:

- **Simpler default taxonomy:** A small number of everyday categories, with an \`Uncertain / Needs Review\` queue instead of filing weak guesses into \`Miscellaneous\`.
- **Optional two-level organization profiles:** For example \`Finance/Invoices\` or \`Work/Projects\`, with maximum depth controlled by the user.
- **Reusable rules and learning from corrections:** Remember user-approved category decisions and deterministic filename rules.
- **Better document understanding:** Scanned PDF OCR, tables, dates, vendors, and invoice metadata.
- **Desktop-quality distribution:** Optional one-click installers and packaged local-model setup.

## Development and testing

\`\`\`bash
python -m pip install -e ".[test,gui]"
python -m pytest -v
python -m build
python -m twine check dist/*
\`\`\`

CI runs Python 3.9, 3.11, and 3.13 on Linux, macOS and Windows, plus packaging, CLI smoke testing, and a Streamlit render smoke test.

## License

Licensed under [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

Created by [Yousef Ebrahimi](https://github.com/yousefebrahimi0).

**If this project saves you time, consider starring the repository.** ⭐
