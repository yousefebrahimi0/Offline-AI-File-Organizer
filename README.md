# 🤖 Offline AI File Organizer

**Organize messy folders with AI—without giving up control of your files.**

Rename and categorize documents based on their contents using **local or cloud LLMs**. Review suggestions before moving anything, monitor folders for new files, and undo previous moves. Available as a **local web dashboard** and a **command-line tool** for Windows, macOS, and Linux.

![Offline AI File Organizer](banner.png)

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)
![Local or cloud LLM](https://img.shields.io/badge/AI-Local%20or%20cloud-purple)

> **Privacy:** With LM Studio, Ollama, or llama.cpp running locally, AI processing can stay on your computer. **Cloud models are optional, but choosing them sends analyzed file content to the configured provider.** The interface itself runs on localhost; this does not make a remote model private.

**Smart Organization v3:** The default profile allows one approved subfolder beneath each category. You can also choose Simple (one level) or Custom (your own approved two-level taxonomy). The AI cannot invent arbitrary folder names. The UI includes a Needs Review queue and reusable sorting rules.

## What you can do

| Feature | User benefit |
| --- | --- |
| **Smart renaming** | Turn cryptic filenames into readable names based on file content and modification month. |
| **Simple categorization** | Route files to configurable category folders under one `Organized/` directory. |
| **Review and approval** | Inspect, rename, re-categorize, or skip suggestions before applying them. |
| **Watch-folder mode** | Analyse newly arriving files after they finish copying. Automatic moves are opt-in. |
| **Parallel analysis** | Analyse several files concurrently using a configurable number of workers. |
| **Undo and safety checks** | Saved plans, SHA-256 fingerprint verification, no-overwrite moves, and undo logs. |
| **Choice of AI** | LM Studio, Ollama, llama.cpp, OpenAI, OpenRouter, Anthropic, Gemini, or compatible endpoints. |
| **Local browser or CLI** | Use an interactive dashboard or automate tasks from a terminal. |

## Example: Before and after

```text
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
```

The example uses optional image analysis. Categories and filenames are AI suggestions, not guaranteed classifications.

## Get started in three steps

**Requirements:** Python 3.9+ and either a local AI server such as [LM Studio](https://lmstudio.ai/) / [Ollama](https://ollama.com/), or API credentials for a supported cloud provider.

### 1. Install from the repository

```bash
git clone https://github.com/yousefebrahimi0/Offline-AI-File-Organizer.git
cd Offline-AI-File-Organizer
python -m pip install -e ".[gui]"
```

This installs the application and its optional Streamlit interface. It does **not** create a standalone Windows EXE or macOS APP.

### 2. Open the local web dashboard

```bash
offline-ai-organizer-gui
```

The app opens in a browser at **http://127.0.0.1:8501** by default, bound to your own computer.

Select a folder, choose your AI provider/model, and click **Analyze folder**. With the default config, LM Studio is expected at `http://localhost:1234/v1`; to use Ollama, change the provider to `ollama` and run its local model server.

### 3. Review → approve → apply

The app first builds suggestions **without moving files**. Review the proposed names and categories, edit anything you dislike, and uncheck files you want to leave untouched. Moving files requires explicit approval. Successfully moved files are recorded in an undo log.

The dashboard also includes **Watch folder** and **History / undo** tabs.

> Start with a folder of **copied test files**, especially before enabling automatic watch-folder moves.

## Smart Organization v3: how it saves time and model tokens

The dashboard's main flow is **choose a folder → choose Smart, Simple, or Custom → review proposed changes → approve**. A persistent **Needs Review** queue stores uncertain or duplicate files without moving or deleting them. Manually reviewed items can be moved to an approved destination and optionally turned into reusable narrow rules.

### Reusable rules and cache

Filename rules are applied **before** calling any LLM; for example:

```yaml
organizer:
  profile: smart
  detect_duplicates: true
  cache_ai_results: true
  naming_template: "{title} ({date})"
  rules:
    - pattern: "*invoice*.pdf"
      category: Finance
      subcategory: Invoices
```

Rules can also include a required text fragment. Add rules through the **Sorting rules** tab. Successful AI classifications are cached locally by content fingerprint, filename, model and taxonomy; unchanged inputs do not need repeated AI inference. Changing the file invalidates its cached result.

The cache and review queue live under `.organizer/` inside the selected folder. They contain filenames and classifications, not extracted full documents or credentials. The app never silently converts one correction into a broad rule.

### Image description and optional document OCR

- A short, structured request asks the model for filename, category, approved subcategory, and a brief rationale. For images it emphasizes **visible objects and readable text**, not guessed identities or unknown locations.
- Images are optionally processed with **local OCR first**. A screenshot or receipt with readable text can skip a multimodal request.
- When a vision request is needed, Pillow creates a **resized in-memory image** (default maximum 1024 pixels, with optimized compression); original images are untouched. Payload bytes are usually smaller, but actual billable vision tokens depend on the provider.
- Digital PDFs sample initial and last pages; scanned PDFs can use **optional PyMuPDF and Tesseract** OCR. DOCX parsing includes small tables.
- Conservative local regexes extract possible document dates and vendor hints; filename templates support `{title}`, `{date}`, `{category}`, `{document_date}`, and `{vendor}`. These hints are not guaranteed correct and should be reviewed.

To enable OCR, install `python -m pip install -e ".[ocr]"` **and the Tesseract executable** separately. We intentionally do not bundle heavyweight OCR foundation models.

References informing the design: [Image Description Toolkit](https://github.com/TheIdeaPlace/Image-Description-Toolkit) for configurable image workflows, and [Awesome OCR LLM](https://github.com/yuliang-liu/awesome-ocr-llm) for OCR research. This project uses original code, without bundling either repository.

### Easier local setup

On Windows run `setup_windows.bat`; on macOS/Linux run `bash setup_macos_linux.sh`. Both create a local Python virtual environment and install the GUI, then launch it. **Python 3.9+ is still required:** these scripts are not signed standalone installers.

## How categorization works today

The organizer recursively scans input subfolders. The **Smart** profile (default) creates only approved category/subcategory paths, such as `Finance/Invoices`. Select **Simple** for one category level or **Custom** to specify a two-level taxonomy.

```text
Selected folder/
└── Organized/
    ├── Work/
    │   ├── Projects/
    │   └── Reports/
    ├── Finance/
    │   ├── Invoices/
    │   ├── Receipts/
    │   └── Statements/
    ├── Personal/
    │   ├── Identity/
    │   └── Medical/
    ├── Education/
    │   └── Research/
    ├── Photos/
    └── Projects/
```

Only categories receiving files are created. These names can be customized in `config.yaml`. Smart can create `Finance/Invoices`, but cannot create a third level such as `Finance/Invoices/2026` or unlimited folders.

The AI must choose from an **approved set of categories**. Unrecognized or ambiguous classifications—including uncertain `Miscellaneous` results—go to the **Needs Review** queue without moving files. This is not a calibrated confidence score.

## Local and cloud AI providers

| Provider | Default use | Where content goes |
| --- | --- | --- |
| LM Studio | Local OpenAI-compatible server | Stays local when configured locally |
| Ollama | Local model server | Stays local when configured locally |
| llama.cpp | Local OpenAI-compatible server | Stays local when configured locally |
| OpenAI / OpenRouter | Cloud API with key | Sent to cloud provider |
| Anthropic / Gemini | Cloud API with key | Sent to cloud provider |
| Custom OpenAI-compatible | User-supplied endpoint | Depends on endpoint |

Configure providers in the dashboard, `config.yaml`, or CLI flags. Prefer environment variables (for example `OPENAI_API_KEY`) for cloud credentials; GUI-entered API keys are not saved in organization plans/logs.

## CLI usage

Install without the web interface:

```bash
python -m pip install -e .
offline-ai-organizer --help
```

**Save and apply an approved plan**

```bash
offline-ai-organizer --folder "./Downloads" --provider ollama --rename --organize --save-plan plan.json
offline-ai-organizer --apply-plan plan.json
```

**Watch for new files (review-only by default)**

```bash
offline-ai-organizer --folder "./Downloads" --watch --rename --organize --workers 3
```

**Explicitly allow automatic moves**

```bash
offline-ai-organizer --folder "./Downloads" --watch --rename --organize --workers 3 --auto-apply
```

Use `--stability-delay 3` to require three seconds of unchanged size and modification time before analysis. Watch mode handles new file events; it does not bulk-scan all existing files at startup. Stop with **Ctrl+C**.

**Undo**

```bash
offline-ai-organizer --undo "./Downloads/organization_log_YYYYMMDD_HHMMSS.json"
```

Undo skips files that changed after a move and refuses to overwrite a file that now occupies the original path. Version 2 plans need regeneration; saved version 3 plans include source fingerprints.

## Supported files

| Type | Extensions | Important notes |
| --- | --- | --- |
| Documents | PDF, DOCX, TXT, MD, RTF, ODT, PPTX | Extraction quality depends on format. PDF reads an initial text preview. |
| Spreadsheets | CSV, XLSX, XLS | Legacy XLS may additionally require `xlrd`. |
| E-books | EPUB | Metadata extraction, not full-book semantic indexing. |
| Images (optional) | PNG, JPG, JPEG, WEBP | Vision LLM support or optional Tesseract OCR. |

Image analysis is disabled by default. Enable it in `config.yaml` or with `--include-images`. Optional OCR dependencies:

```bash
python -m pip install -e ".[ocr]"
```

Tesseract itself must be installed separately. **Optional scanned-PDF OCR** uses PyMuPDF to render pages before Tesseract extraction. Without the optional OCR dependencies, scanned PDFs fall back to filename-based context. Audio/video analysis and semantic search are not implemented.

## Configuration

Edit [config.yaml](config.yaml) to select your LLM, adjust ignored folders, configure categories, and set watcher defaults. For example:

```yaml
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
```

## Safety and limitations

- **Review first:** Regular GUI analysis and default watch mode create proposals rather than moving files automatically.
- **No target overwrite:** Source fingerprints, root-bound plans, and collision checks protect against many accidental changes.
- **Undo is conditional:** Files must remain unchanged and their previous locations must be available.
- **Not a single transaction:** A batch can partially succeed if later moves fail; consult the execution log.
- **AI can be wrong:** Review sensitive documents and category suggestions before applying changes.
- **Local app ≠ local inference:** Remote cloud models can receive the file content analyzed by the program.
- **Not yet a full file manager:** No arbitrary-depth category trees, automatic duplicate deletion, semantic search, or standalone desktop installers. Duplicate detection queues matching files for review.

## What could come next?

The v3 release already includes a review queue, Smart/Simple/Custom two-level profiles, rules that avoid AI calls, duplicate detection, locally extracted document hints, optional scanned-PDF OCR, and manual approval workflows.

Still planned: **native signed Windows/macOS installers**, semantic document search, optional heavier OCR engines for complex layouts, and better on-device model onboarding.

## Development and testing

```bash
python -m pip install -e ".[test,gui]"
python -m pytest -v
python -m build
python -m twine check dist/*
```

CI runs Python 3.9, 3.11, and 3.13 on Linux, macOS and Windows, plus packaging, CLI smoke testing, and a Streamlit render smoke test.

## License

Licensed under [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

Created by [Yousef Ebrahimi](https://github.com/yousefebrahimi0).

**If this project saves you time, consider starring the repository.** ⭐
