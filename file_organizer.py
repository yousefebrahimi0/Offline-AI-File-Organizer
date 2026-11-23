"""
Offline AI-Powered File Organizer and Renamer by Yousef; https://github.com/yousefebrahimi0/
Uses any local or cloud LLM (LM Studio, Ollama, llama.cpp, OpenAI, OpenRouter, Anthropic, Gemini)
to intelligently rename and organize documents and optional images with dry-run plan caching and undo.
"""

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import threading
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

from smart_organizer import AnalysisCache, DuplicateIndex, ReviewQueue, RuleBook, Taxonomy, Workspace, SMART_SUBCATEGORIES
from document_intelligence import document_hints, exif_hint, image_ocr, optimized_image, scanned_pdf_ocr

# Optional document & OCR libraries (graceful fallback per format)
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import docx
except ImportError:
    docx = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from ebooklib import epub
except ImportError:
    epub = None

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None


DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".epub",
    ".csv",
    ".xlsx",
    ".xls",
    ".md",
    ".rtf",
    ".odt",
    ".pptx",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

SUPPORTED_EXTENSIONS = DOCUMENT_EXTENSIONS

DEFAULT_CATEGORIES = [
    "Work",
    "Personal",
    "Finance",
    "Medical",
    "Education",
    "Legal",
    "Photos",
    "Projects",
    "Archive",
    "Miscellaneous",
]

PROVIDER_DEFAULTS = {
    "lm_studio": {
        "base_url": "http://localhost:1234/v1",
        "env_key": None,
        "api_type": "openai",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "env_key": None,
        "api_type": "openai",
    },
    "llama_cpp": {
        "base_url": "http://localhost:8080/v1",
        "env_key": None,
        "api_type": "openai",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "api_type": "openai",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "api_type": "openai",
    },
    "openai_compatible": {
        "base_url": "http://localhost:1234/v1",
        "env_key": "LLM_API_KEY",
        "api_type": "openai",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
        "api_type": "anthropic",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "env_key": "GEMINI_API_KEY",
        "api_type": "gemini",
    },
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load YAML configuration with safe defaults."""
    defaults: Dict[str, Any] = {
        "llm": {
            "provider": "lm_studio",
            "base_url": "",
            "model": "auto",
            "api_key": "",
            "temperature": 0.2,
            "max_tokens": 160,
            "timeout": 45,
        },
        "organizer": {
            "max_content_length": 3000,
            "organize_folder_name": "Organized",
            "enable_images": False,
            "use_vision_model": True,
            "ignore_folders": [
                "Organized",
                ".git",
                "__pycache__",
                "node_modules",
                ".venv",
                "venv",
            ],
            "categories": list(DEFAULT_CATEGORIES),
            "profile": "smart",
            "smart_subcategories": dict(SMART_SUBCATEGORIES),
            "detect_duplicates": True,
            "cache_ai_results": True,
            "naming_template": "{title} ({date})",
            "image_max_dimension": 1024,
            "image_quality": 76,
            "ocr_first_images": True,
            "ocr_scanned_pdfs": True,
            "rules": [],
        },
    }

    path = Path(config_path) if config_path else Path(__file__).parent / "config.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        for section in ("llm", "organizer"):
            if isinstance(user_cfg.get(section), dict):
                defaults[section].update(user_cfg[section])

    return defaults


class UniversalLLMClient:
    """Unified client supporting LM Studio, Ollama, llama.cpp, OpenAI, OpenRouter, Anthropic, Gemini."""

    def __init__(
        self,
        provider: str = "lm_studio",
        base_url: str = "",
        model: str = "auto",
        api_key: str = "",
        temperature: float = 0.2,
        max_tokens: int = 120,
        timeout: int = 45,
        image_max_dimension: int = 1024,
        image_quality: int = 76,
    ):
        self.provider = (provider or "lm_studio").lower().strip()
        preset = PROVIDER_DEFAULTS.get(self.provider, PROVIDER_DEFAULTS["openai_compatible"])
        self.api_type = preset["api_type"]
        self.base_url = (base_url or preset["base_url"]).rstrip("/")
        self.model = model or "auto"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.image_max_dimension = image_max_dimension
        self.image_quality = image_quality

        env_key_name = preset.get("env_key")
        self.api_key = (
            api_key
            or os.environ.get("LLM_API_KEY", "")
            or (os.environ.get(env_key_name, "") if env_key_name else "")
        )

    def _openai_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def list_models(self) -> List[str]:
        """Fetch available model IDs from OpenAI-compatible endpoints."""
        if self.api_type != "openai":
            return [self.model] if self.model and self.model != "auto" else []
        try:
            resp = requests.get(
                f"{self.base_url}/models",
                headers=self._openai_headers(),
                timeout=min(self.timeout, 10),
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return [m["id"] for m in data if isinstance(m, dict) and "id" in m]
        except Exception:
            pass
        return []

    def test_connection(self) -> Tuple[bool, str]:
        """Verify provider connectivity and resolve 'auto' model selection."""
        if self.api_type == "openai":
            models = self.list_models()
            if models:
                if self.model == "auto":
                    self.model = models[0]
                return True, f"Connected to {self.provider} (model: {self.model})"
            if self.model != "auto":
                return True, f"Configured {self.provider} with model: {self.model}"
            return (
                False,
                f"Cannot reach {self.base_url}/models or no models loaded. "
                f"Start {self.provider} or specify a model in config.yaml.",
            )

        if self.api_type in ("anthropic", "gemini"):
            if not self.api_key:
                return False, f"Missing API key for provider '{self.provider}'."
            if self.model == "auto":
                self.model = (
                    "claude-3-5-haiku-latest"
                    if self.api_type == "anthropic"
                    else "gemini-2.0-flash"
                )
            return True, f"Configured {self.provider} (model: {self.model})"

        return False, f"Unsupported provider: {self.provider}"

    def chat(self, prompt: str, image_path: Optional[Path] = None) -> Optional[str]:
        """Send a single-turn user prompt (with optional image for VLM models)."""
        b64_image = None
        mime_type = "image/jpeg"
        if image_path is not None and image_path.exists():
            mime_type, b64_image = optimized_image(
                image_path, self.image_max_dimension, self.image_quality
            )

        try:
            if self.api_type == "openai":
                url = (
                    self.base_url
                    if self.base_url.endswith("/chat/completions")
                    else f"{self.base_url}/chat/completions"
                )
                if b64_image:
                    user_content: Any = [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                        },
                    ]
                else:
                    user_content = prompt

                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": user_content}],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }
                resp = requests.post(
                    url, headers=self._openai_headers(), json=payload, timeout=self.timeout
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
                print(f"AI request failed ({resp.status_code}): {resp.text[:200]}")
                return None

            if self.api_type == "anthropic":
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                }
                if b64_image:
                    content_blocks: Any = [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_image,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ]
                else:
                    content_blocks = prompt

                payload = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "messages": [{"role": "user", "content": content_blocks}],
                }
                resp = requests.post(
                    self.base_url, headers=headers, json=payload, timeout=self.timeout
                )
                if resp.status_code == 200:
                    blocks = resp.json().get("content", [])
                    return "".join(b.get("text", "") for b in blocks).strip()
                print(f"Anthropic request failed ({resp.status_code}): {resp.text[:200]}")
                return None

            if self.api_type == "gemini":
                url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
                parts: List[Dict[str, Any]] = [{"text": prompt}]
                if b64_image:
                    parts.append({"inline_data": {"mime_type": mime_type, "data": b64_image}})
                payload = {
                    "contents": [{"parts": parts}],
                    "generationConfig": {
                        "temperature": self.temperature,
                        "maxOutputTokens": self.max_tokens,
                    },
                }
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    candidates = resp.json().get("candidates", [])
                    if candidates:
                        resp_parts = candidates[0].get("content", {}).get("parts", [])
                        return "".join(p.get("text", "") for p in resp_parts).strip()
                print(f"Gemini request failed ({resp.status_code}): {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"Error connecting to LLM ({self.provider}): {e}")
            return None
        return None


class FileOrganizer:
    def __init__(
        self,
        root_folder: str,
        llm_client: Optional[UniversalLLMClient] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.root_folder = Path(root_folder).resolve()
        self.config = config or load_config()
        org_cfg = self.config["organizer"]

        self.max_content_length = int(org_cfg.get("max_content_length", 3000))
        self.organize_folder_name = org_cfg.get("organize_folder_name", "Organized")
        self.enable_images = bool(org_cfg.get("enable_images", False))
        self.use_vision_model = bool(org_cfg.get("use_vision_model", True))
        self.ignore_folders = set(org_cfg.get("ignore_folders", ["Organized", ".git"]))
        self.ignore_folders.add(self.organize_folder_name)
        self.ignore_folders.add(".organizer")
        self.categories = list(org_cfg.get("categories", DEFAULT_CATEGORIES))
        self.profile = org_cfg.get("profile", "smart")
        subcategories = org_cfg.get("smart_subcategories", SMART_SUBCATEGORIES)
        self.taxonomy = Taxonomy(self.categories, self.profile, subcategories)
        self.workspace = Workspace(self.root_folder)
        self.rulebook = RuleBook(self.workspace, self.taxonomy, org_cfg.get("rules", []))
        self.review_queue = ReviewQueue(self.workspace)
        self.analysis_cache = AnalysisCache(self.workspace)
        self.cache_ai_results = bool(org_cfg.get("cache_ai_results", True))
        self.detect_duplicates = bool(org_cfg.get("detect_duplicates", True))
        self.duplicate_index = DuplicateIndex()
        self._duplicate_index_ready = False
        self._duplicate_lock = threading.Lock()
        self.naming_template = str(org_cfg.get("naming_template", "{title} ({date})"))
        self.ocr_first_images = bool(org_cfg.get("ocr_first_images", True))
        self.ocr_scanned_pdfs = bool(org_cfg.get("ocr_scanned_pdfs", True))

        if llm_client is not None:
            self.llm = llm_client
        else:
            llm_cfg = self.config["llm"]
            self.llm = UniversalLLMClient(
                provider=llm_cfg.get("provider", "lm_studio"),
                base_url=llm_cfg.get("base_url", ""),
                model=llm_cfg.get("model", "auto"),
                api_key=llm_cfg.get("api_key", ""),
                temperature=float(llm_cfg.get("temperature", 0.2)),
                max_tokens=int(llm_cfg.get("max_tokens", 120)),
                timeout=int(llm_cfg.get("timeout", 45)),
                image_max_dimension=int(org_cfg.get("image_max_dimension", 1024)),
                image_quality=int(org_cfg.get("image_quality", 76)),
            )

        self.planned_actions: List[Dict[str, str]] = []

        self.executed_log: List[Dict[str, Any]] = []

    @staticmethod
    def _path_is_within(path: Path, root: Path) -> bool:
        """Return True only when the resolved path stays inside root."""
        try:
            Path(path).resolve(strict=False).relative_to(Path(root).resolve(strict=False))
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _file_fingerprint(file_path: Path) -> Dict[str, Any]:
        """Capture content and metadata, rejecting files that change while read."""
        if file_path.is_symlink() or not file_path.is_file():
            raise ValueError(f"Not a regular file: {file_path}")
        before = file_path.stat()
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            after_open = os.fstat(stream.fileno())
        after = file_path.stat()

        def identity(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

        if identity(before) != identity(opened) or identity(opened) != identity(after_open) or identity(after_open) != identity(after):
            raise ValueError(f"File changed while being fingerprinted: {file_path}")

        return {
            "size": after.st_size,
            "mtime_ns": after.st_mtime_ns,
            "sha256": digest.hexdigest(),
        }

    @staticmethod
    def _fingerprint_matches(actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
        """Compare every field stored in a version 3 plan/log."""
        return (
            isinstance(expected, dict)
            and actual.get("size") == expected.get("size")
            and actual.get("mtime_ns") == expected.get("mtime_ns")
            and actual.get("sha256") == expected.get("sha256")
        )

    @staticmethod
    def _move_no_overwrite(
        source: Path,
        target: Path,
        expected_fingerprint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Move a regular file without replacing an existing destination.
        Exclusive target creation prevents overwrite races and also supports
        moves across filesystems. If anything fails before source removal,
        the source remains intact and the partial target is removed.
        """
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Source is not a regular file: {source}")
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Destination already exists: {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        created_target = False
        digest = hashlib.sha256()

        try:
            with source.open("rb") as source_stream:
                before_fd = os.fstat(source_stream.fileno())
                with target.open("xb") as target_stream:
                    created_target = True
                    for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                        target_stream.write(chunk)
                    target_stream.flush()
                    os.fsync(target_stream.fileno())

                after_fd = os.fstat(source_stream.fileno())
                current_source = source.stat()

                def identity(info):
                    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

                if identity(before_fd) != identity(after_fd) or identity(after_fd) != identity(current_source):
                    raise ValueError(f"Source changed while it was being moved: {source}")

                if expected_fingerprint:
                    if (
                        after_fd.st_size != expected_fingerprint.get("size")
                        or digest.hexdigest() != expected_fingerprint.get("sha256")
                    ):
                        raise ValueError(f"File contents no longer match the approved plan: {source}")

                shutil.copystat(source, target, follow_symlinks=False)
                target_fingerprint = FileOrganizer._file_fingerprint(target)

                # Confirm the source has not changed while its handle was open.
                final_source = source.stat()
                if identity(after_fd) != identity(final_source):
                    raise ValueError(f"Source changed before it could be removed: {source}")

            # Windows refuses unlinking a file while this process still has
            # its source handle open. Close it before the final identity check.
            if identity(after_fd) != identity(source.stat()):
                raise ValueError(f"Source changed before it could be removed: {source}")
            source.unlink()
            return target_fingerprint
        except Exception:
            if created_target:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def _validate_plan_paths(
        self, action: Dict[str, Any], require_source: bool = False
    ) -> Tuple[Path, Path]:
        """Validate both paths against the selected root before file operations."""
        if not isinstance(action, dict):
            raise ValueError("Plan action must be a JSON object.")

        old_value, new_value = action.get("old_path"), action.get("new_path")
        if not isinstance(old_value, str) or not isinstance(new_value, str):
            raise ValueError("Plan action is missing old_path or new_path.")

        old_path, new_path = Path(old_value), Path(new_value)
        if not old_path.is_absolute() or not new_path.is_absolute():
            raise ValueError("Plan paths must be absolute.")
        if old_path.is_symlink() or new_path.is_symlink():
            raise ValueError("Symbolic-link paths are not allowed in plans.")
        if not self._path_is_within(old_path, self.root_folder):
            raise ValueError(f"Source path escapes the selected folder: {old_path}")
        if not self._path_is_within(new_path, self.root_folder):
            raise ValueError(f"Destination path escapes the selected folder: {new_path}")
        if old_path.resolve(strict=False) == self.root_folder or new_path.resolve(strict=False) == self.root_folder:
            raise ValueError("A plan cannot use the selected root folder as a file path.")
        if require_source and not old_path.is_file():
            raise FileNotFoundError(f"Planned source file is missing: {old_path}")
        # Organizing may use a top category and one vetted subcategory, never deeper.
        if action.get("category") and action.get("subcategory"):
            allowed = self.taxonomy.target_dir(
                self.root_folder, self.organize_folder_name,
                action["category"], action["subcategory"],
            )
            if new_path.parent.resolve(strict=False) != allowed.resolve(strict=False):
                raise ValueError("Plan destination violates approved folder depth.")
        return old_path, new_path

    def _preflight_plan(self) -> List[Tuple[Dict[str, Any], Path, Path]]:
        """Validate every action before changing any file."""
        if not self.root_folder.is_dir():
            raise NotADirectoryError(f"Selected folder does not exist: {self.root_folder}")

        validated = []
        seen_sources, seen_targets = set(), set()
        for action in self.planned_actions:
            old_path, new_path = self._validate_plan_paths(action, require_source=True)
            source_key = os.path.normcase(str(old_path.resolve()))
            target_key = os.path.normcase(str(new_path.resolve(strict=False)))

            if source_key in seen_sources:
                raise ValueError(f"Plan contains the same source more than once: {old_path}")
            if target_key in seen_targets:
                raise ValueError(f"Plan contains duplicate destinations: {new_path}")
            if source_key == target_key:
                raise ValueError(f"Plan contains a no-op action: {old_path}")
            if new_path.exists() or new_path.is_symlink():
                raise FileExistsError(f"Destination already exists: {new_path}")
            if not self._path_is_within(new_path.parent, self.root_folder):
                raise ValueError(f"Destination directory escapes the selected folder: {new_path.parent}")

            expected = action.get("source_fingerprint")
            if (
                not isinstance(expected, dict)
                or not isinstance(expected.get("size"), int)
                or not isinstance(expected.get("mtime_ns"), int)
                or not isinstance(expected.get("sha256"), str)
                or len(expected["sha256"]) != 64
            ):
                raise ValueError(f"Plan has no valid source fingerprint: {old_path}")

            actual = self._file_fingerprint(old_path)
            if not self._fingerprint_matches(actual, expected):
                raise ValueError(f"Source file changed since the plan was created: {old_path}")

            seen_sources.add(source_key)
            seen_targets.add(target_key)
            validated.append((action, old_path, new_path))
        return validated

    def _active_extensions(self) -> set:
        if self.enable_images:
            return DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS
        return DOCUMENT_EXTENSIONS

    def _is_ignored(self, file_path: Path) -> bool:
        """Skip files inside Organized/ or other ignored directories."""
        try:
            rel_parts = file_path.relative_to(self.root_folder).parts[:-1]
        except ValueError:
            rel_parts = file_path.parts[:-1]
        return any(part in self.ignore_folders for part in rel_parts)

    def discover_files(self) -> List[Path]:
        """Find all supported files while excluding ignored directories."""
        allowed = self._active_extensions()
        files = []
        for file_path in sorted(self.root_folder.rglob("*")):
            if (
                file_path.is_file()
                and not file_path.is_symlink()
                and self._path_is_within(file_path, self.root_folder)
                and file_path.suffix.lower() in allowed
                and not self._is_ignored(file_path)
            ):
                files.append(file_path)
        return files

    @staticmethod
    def _extract_rtf(file_path: Path) -> str:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
        text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
        text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
        text = re.sub(r"[{}]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_odt(file_path: Path) -> str:
        with zipfile.ZipFile(file_path, "r") as zf:
            xml_bytes = zf.read("content.xml")
        root = ET.fromstring(xml_bytes)
        return " ".join(t.strip() for t in root.itertext() if t and t.strip())

    @staticmethod
    def _extract_pptx(file_path: Path) -> str:
        chunks = []
        with zipfile.ZipFile(file_path, "r") as zf:
            slide_names = sorted(
                n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            )
            for slide in slide_names[:10]:
                root = ET.fromstring(zf.read(slide))
                slide_text = " ".join(t.strip() for t in root.itertext() if t and t.strip())
                if slide_text:
                    chunks.append(slide_text)
        return " ".join(chunks)

    def extract_text_content(self, file_path: Path) -> str:
        """Extract text content safely from supported file types."""
        ext = file_path.suffix.lower()
        content = ""

        try:
            if ext == ".pdf" and PdfReader is not None:
                with open(file_path, "rb") as f:
                    pdf_reader = PdfReader(f)
                    chunks = []
                    pages = pdf_reader.pages
                    page_count = len(pages)
                    indices = sorted({0, 1, page_count - 1} & set(range(page_count)))
                    for index in indices:
                        text = pages[index].extract_text() or ""
                        if text:
                            chunks.append(text)
                    content = " ".join(chunks)
                if not content.strip() and self.ocr_scanned_pdfs:
                    content = scanned_pdf_ocr(file_path)

            elif ext == ".docx" and docx is not None:
                doc = docx.Document(file_path)
                paragraphs = [para.text for para in doc.paragraphs[:20] if para.text]
                tables = []
                for table in doc.tables[:3]:
                    for row in table.rows[:8]:
                        tables.append(" | ".join(cell.text.strip() for cell in row.cells))
                content = " ".join(paragraphs + tables)

            elif ext in (".txt", ".md"):
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(self.max_content_length)

            elif ext == ".rtf":
                content = self._extract_rtf(file_path)

            elif ext == ".odt":
                content = self._extract_odt(file_path)

            elif ext == ".pptx":
                content = self._extract_pptx(file_path)

            elif ext == ".csv" and pd is not None:
                df = pd.read_csv(file_path, nrows=10)
                content = f"CSV with columns: {', '.join(map(str, df.columns.tolist()))}\n"
                content += df.head(5).to_string()

            elif ext in (".xlsx", ".xls") and pd is not None:
                df = pd.read_excel(file_path, nrows=10)
                content = f"Excel with columns: {', '.join(map(str, df.columns.tolist()))}\n"
                content += df.head(5).to_string()

            elif ext == ".epub" and epub is not None:
                book = epub.read_epub(str(file_path))
                title = book.get_metadata("DC", "title")
                content = f"EPUB Book: {title[0][0] if title else 'Unknown'}"

            elif ext in IMAGE_EXTENSIONS:
                ocr_text = image_ocr(file_path, self.max_content_length)
                hint = exif_hint(file_path)
                if ocr_text:
                    content = f"Image OCR: {ocr_text}. {hint}"
                else:
                    content = f"Image file: {file_path.stem}. {hint}"

        except Exception as e:
            print(f"Error extracting content from {file_path.name}: {e}")
            content = f"File: {file_path.stem}"

        if not content.strip():
            content = f"File: {file_path.stem}"

        return content[: self.max_content_length]

    def sanitize_filename(self, name: str, max_len: int = 60) -> str:
        """Ensure filename is safe across Windows/macOS/Linux (keeps Unicode/Persian)."""
        name = re.sub(r'[<>:"/\\|?*\r\n\t]', "", name)
        name = re.sub(r"\s+", " ", name).strip(". ")
        return name[:max_len].strip(". ")

    def sanitize_category(self, raw_category: str) -> str:
        """Validate AI category against allowed list, preventing path traversal or chatty output."""
        if not raw_category:
            return "Miscellaneous"
        cleaned = self.sanitize_filename(raw_category, max_len=40)
        lookup = {c.lower(): c for c in self.categories}
        if cleaned.lower() in lookup:
            return lookup[cleaned.lower()]
        for cat_lower, cat_proper in lookup.items():
            if cat_lower in cleaned.lower():
                return cat_proper
        return "Miscellaneous"

    def get_file_date_string(self, file_path: Path) -> str:
        timestamp = os.path.getmtime(file_path)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m")

    def _parse_json_response(self, raw: str) -> Dict[str, str]:
        """Extract JSON object from LLM output, tolerating markdown code fences."""
        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if v is not None}
        except json.JSONDecodeError:
            pass
        return {}

    def _ensure_duplicates(self) -> None:
        if not self.detect_duplicates or self._duplicate_index_ready:
            return
        with self._duplicate_lock:
            if not self._duplicate_index_ready:
                self.duplicate_index.scan_organized(
                    self.root_folder / self.organize_folder_name,
                    self._file_fingerprint,
                    self._active_extensions(),
                )
                self._duplicate_index_ready = True

    def duplicate_of(self, path: Path, fingerprint: Dict[str, Any]) -> Optional[str]:
        if not self.detect_duplicates:
            return None
        self._ensure_duplicates()
        return self.duplicate_index.find_or_register(path, fingerprint)

    def format_target_name(
        self, title: str, file_path: Path, category: str = "",
        document_date: str = "", vendor: str = ""
    ) -> str:
        """Only known template placeholders are expanded, never arbitrary Python fields."""
        title = self.sanitize_filename(title, max_len=80)
        date = self.get_file_date_string(file_path)
        mapping = {
            "title": title, "date": date, "category": category or "",
            "document_date": document_date or date,
            "vendor": self.sanitize_filename(vendor, max_len=50),
        }
        value = self.naming_template
        for field in ("title", "date", "category", "document_date", "vendor"):
            value = value.replace("{" + field + "}", mapping[field])
        if "{" in value or "}" in value:
            raise ValueError("Invalid naming template placeholder.")
        base = self.sanitize_filename(value, max_len=180)
        return f"{base}{file_path.suffix}" if base else file_path.name

    def suggest_file(
        self, file_path: Path, rename: bool = True, organize: bool = True,
        fingerprint: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, str]]:
        """One structured AI request at most; deterministic approved rules bypass AI."""
        file_path = Path(file_path)
        # Cheap filename-only rules avoid both extraction and model tokens.
        rule = self.rulebook.match(file_path)
        if rule is None and any(r.get("contains") for r in self.rulebook.list_rules() if isinstance(r, dict)):
            preview = self.extract_text_content(file_path)
            rule = self.rulebook.match(file_path, preview)
        if rule:
            return {
                "filename": self.sanitize_filename(file_path.stem, max_len=60) if rename else "",
                "category": rule["category"] if organize else "",
                "subcategory": rule["subcategory"] if organize else "",
                "reason": f"Matched filename rule: {rule['pattern']}",
                "source": "rule",
            }

        fingerprint = fingerprint or self._file_fingerprint(file_path)
        cache_key = AnalysisCache.key([
            "smart-v3.1", fingerprint["sha256"], file_path.name,
            self.get_file_date_string(file_path), rename, organize,
            self.profile, self.taxonomy.subcategories, self.categories,
            self.use_vision_model, self.ocr_first_images,
            getattr(self.llm, "provider", ""), getattr(self.llm, "model", ""),
        ])
        if self.cache_ai_results:
            cached = self.analysis_cache.get(cache_key)
            if cached:
                cached["source"] = "cache"
                return cached

        content = self.extract_text_content(file_path)
        hints = document_hints(content)
        is_image = file_path.suffix.lower() in IMAGE_EXTENSIONS
        image_arg = None
        if is_image and self.use_vision_model:
            # OCR is cheaper than a vision request for readable screenshots/receipts.
            has_ocr_text = "Image OCR:" in content and len(content.split("Image OCR:", 1)[1].strip()) >= 32
            if not self.ocr_first_images or not has_ocr_text:
                image_arg = file_path

        if is_image and image_arg is None and content.startswith("Image file:"):
            self.review_queue.add(file_path, "Image has no readable OCR text and vision is disabled.")
            return None

        prompts = self.taxonomy.prompt_categories() if organize else "not needed"
        image_instructions = (
            "For images, describe only visible subjects, objects and readable text. "
            "Do not guess identity or an unknown location. "
            if is_image else ""
        )
        prompt = (
            'Classify a file. Output ONLY JSON keys filename, category, subcategory, reason. '
            'filename: accurate 2-7 words, no extension; reason: max 8 words. '
            'If unsure, category "Needs Review". Never invent dates or text. '
            'Use only allowed categories/subcategories; subcategory can be empty. '
            f'{image_instructions}'
            f'Allowed folders: {prompts}. '
            f'Original: {file_path.stem}; modification: {self.get_file_date_string(file_path)}. '
            f'Metadata hints: {json.dumps(hints, separators=(",", ":")) if hints else "none"}. '
            f'Preview: {content[:900]}'
        )
        raw = self.llm.chat(prompt, image_path=image_arg)
        parsed = self._parse_json_response(raw or "")
        if not parsed:
            self.review_queue.add(file_path, "Model did not return valid classification JSON.")
            return None
        title = self.sanitize_filename(parsed.get("filename", ""), max_len=60) if rename else ""
        if rename and not title:
            self.review_queue.add(file_path, "Model did not provide a useful filename.")
            return None

        category, subcategory = "", ""
        if organize:
            category = self.taxonomy.category(parsed.get("category", ""))
            if category is None or category == "Miscellaneous":
                self.review_queue.add(file_path, "AI category uncertain or outside approved categories.")
                return None
            subcategory = self.taxonomy.subcategory(category, parsed.get("subcategory", ""))
            if subcategory is None:
                self.review_queue.add(file_path, "AI subcategory outside approved taxonomy.")
                return None
        result = {
            "filename": title, "category": category,
            "subcategory": subcategory,
            "reason": parsed.get("reason", "")[:100],
            "source": "ai",
            "document_date": hints.get("document_date", ""),
            "vendor": hints.get("vendor", ""),
        }
        if self.cache_ai_results:
            self.analysis_cache.put(cache_key, result)
        return result

    def analyze_file(
        self, file_path: Path, rename: bool = True, organize: bool = True
    ) -> Tuple[Optional[str], Optional[str]]:
        """Compatibility interface for callers needing only name/category."""
        result = self.suggest_file(file_path, rename=rename, organize=organize)
        return (result["filename"] or None, result["category"] or None) if result else (None, None)

    def target_directory(self, path: Path, category: str, subcategory: str, organize: bool) -> Path:
        return (
            self.taxonomy.target_dir(self.root_folder, self.organize_folder_name, category, subcategory)
            if organize else path.parent
        )

    def build_plan(self, rename: bool = True, organize: bool = False) -> List[Dict[str, Any]]:
        """Build an approved-only v3 dry-run plan; queue ambiguous and duplicate inputs."""
        self.planned_actions = []
        files = self.discover_files()
        print(f"\nFound {len(files)} supported files")
        reserved = set()

        for path in files:
            print(f"\nAnalyzing: {path.name}")
            try:
                before = self._file_fingerprint(path)
                duplicate = self.duplicate_of(path, before)
                if duplicate:
                    self.review_queue.add(path, f"Identical file already exists: {duplicate}", before)
                    print(f"  ⚠️  Duplicate content: {duplicate}")
                    continue

                details = self.suggest_file(
                    path, rename=rename, organize=organize, fingerprint=before
                )
                if not details:
                    print(f"  ⚠️  Needs review: {path.name} (left untouched)")
                    continue

                after = self._file_fingerprint(path)
                if not self._fingerprint_matches(before, after):
                    self.review_queue.add(path, "File changed during analysis.", after)
                    continue

                target_dir = self.target_directory(
                    path, details["category"], details["subcategory"], organize,
                )
                new_name = (
                    self.format_target_name(
                        details["filename"], path, details["category"],
                        details.get("document_date", ""), details.get("vendor", "")
                    )
                    if rename else path.name
                )
                desired = target_dir / new_name
                target = desired
                counter = 1
                while (
                    (target.exists() and target != path)
                    or os.path.normcase(str(target.resolve(strict=False))) in reserved
                ):
                    target = desired.with_name(f"{desired.stem} [{counter}]{desired.suffix}")
                    counter += 1
                reserved.add(os.path.normcase(str(target.resolve(strict=False))))
                if target.resolve(strict=False) == path.resolve():
                    continue

                action = {
                    "old_path": str(path.resolve()),
                    "new_path": str(target.resolve(strict=False)),
                    "category": details["category"],
                    "subcategory": details["subcategory"],
                    "reason": details["reason"],
                    "source": details["source"],
                    "source_fingerprint": before,
                }
                self._validate_plan_paths(action)
                self.planned_actions.append(action)
                self.review_queue.dismiss(str(path.resolve()))
                print(f"  → Planned: {path.name} => {target.relative_to(self.root_folder)}")
            except (OSError, ValueError) as exc:
                self.review_queue.add(path, f"Processing failed: {exc}")
                print(f"  ⚠️  Skipped: {exc}")

        return self.planned_actions

    def save_plan(self, plan_file_path: str) -> Path:
        """Save a versioned dry-run plan with source fingerprints."""
        path = Path(plan_file_path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 3,
                    "root_folder": str(self.root_folder),
                    "timestamp": datetime.now().isoformat(),
                    "actions": self.planned_actions,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"\n✓ Plan saved to: {path}")
        return path

    def load_plan(self, plan_file_path: str) -> List[Dict[str, Any]]:
        """Load and validate a version 3 plan for this exact root folder."""
        with open(plan_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict) or data.get("version") != 3:
            raise ValueError(
                "Unsupported or unsafe plan format. Re-create the dry-run plan with this version."
            )
        plan_root = Path(data.get("root_folder", "")).resolve(strict=False)
        if plan_root != self.root_folder:
            raise ValueError(
                f"Plan belongs to a different folder ({plan_root}); selected folder is {self.root_folder}."
            )

        actions = data.get("actions")
        if not isinstance(actions, list):
            raise ValueError("Plan actions must be a JSON array.")
        for action in actions:
            self._validate_plan_paths(action, require_source=False)
            fingerprint = action.get("source_fingerprint")
            if (
                not isinstance(fingerprint, dict)
                or not isinstance(fingerprint.get("size"), int)
                or not isinstance(fingerprint.get("mtime_ns"), int)
                or not isinstance(fingerprint.get("sha256"), str)
                or len(fingerprint["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in fingerprint["sha256"].lower())
            ):
                raise ValueError("Plan contains a missing or invalid source fingerprint.")

        self.planned_actions = actions
        return self.planned_actions

    def apply_plan(self, save_log: bool = True) -> Optional[Path]:
        """Preflight the whole plan, then move files without overwriting targets."""
        validated = self._preflight_plan()
        self.executed_log = []

        for action, old_path, new_path in validated:
            try:
                moved_fingerprint = self._move_no_overwrite(
                    old_path, new_path, expected_fingerprint=action["source_fingerprint"]
                )
                executed_action = dict(action)
                executed_action["result_fingerprint"] = moved_fingerprint
                self.executed_log.append(executed_action)
                print(f"  ✓ Applied: {old_path.name}  ==>  {new_path.name}")
            except Exception as e:
                print(f"  ✗ Error moving {old_path.name}: {e}")

        if save_log and self.executed_log:
            log_file = (
                self.root_folder
                / f"organization_log_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            )
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "version": 3,
                        "root_folder": str(self.root_folder),
                        "timestamp": datetime.now().isoformat(),
                        "actions": self.executed_log,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            print(f"\n✓ Log saved to: {log_file}")
            return log_file
        return None

    @staticmethod
    def undo_from_log(log_file_path: str) -> int:
        """Undo safely; never overwrite originals or modified organized files."""
        log_path = Path(log_file_path).resolve(strict=False)
        if not log_path.is_file():
            print(f"❌ Log file not found: {log_path}")
            return 0

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"❌ Could not read undo log: {e}")
            return 0

        if not isinstance(data, dict) or data.get("version") not in (2, 3):
            print("❌ Unsupported undo log format.")
            return 0

        root_value = data.get("root_folder") or str(log_path.parent)
        root_folder = Path(root_value).resolve(strict=False)
        if log_path.parent != root_folder:
            print("❌ Undo log must remain in the organization root folder.")
            return 0

        actions = data.get("actions", [])
        if not isinstance(actions, list):
            print("❌ Undo log actions must be a JSON array.")
            return 0

        reverted = 0
        for action in reversed(actions):
            try:
                if not isinstance(action, dict):
                    raise ValueError("Invalid action in undo log.")
                old_value, new_value = action.get("old_path"), action.get("new_path")
                if not isinstance(old_value, str) or not isinstance(new_value, str):
                    raise ValueError("Undo action is missing a source or destination path.")
                old_path, new_path = Path(old_value), Path(new_value)

                if not old_path.is_absolute() or not new_path.is_absolute():
                    raise ValueError("Undo log paths must be absolute.")
                if old_path.is_symlink() or new_path.is_symlink():
                    raise ValueError("Symbolic-link paths are not allowed in undo logs.")
                if not FileOrganizer._path_is_within(old_path, root_folder):
                    raise ValueError(f"Original path escapes the organization root: {old_path}")
                if not FileOrganizer._path_is_within(new_path, root_folder):
                    raise ValueError(f"Organized path escapes the organization root: {new_path}")
                if old_path.exists() or old_path.is_symlink():
                    print(f"  ⚠️  Conflict; original path already exists, not overwritten: {old_path}")
                    continue
                if not new_path.is_file():
                    print(f"  ⚠️  Organized file is missing; cannot restore: {new_path}")
                    continue

                expected = action.get("result_fingerprint") or action.get("source_fingerprint")
                if expected:
                    actual = FileOrganizer._file_fingerprint(new_path)
                    if not FileOrganizer._fingerprint_matches(actual, expected):
                        print(f"  ⚠️  File was modified after organization; not restored: {new_path}")
                        continue

                FileOrganizer._move_no_overwrite(
                    new_path, old_path, expected_fingerprint=expected
                )
                reverted += 1
                print(f"  ↩ Restored: {new_path.name}  ==>  {old_path}")
            except Exception as e:
                print(f"  ✗ Could not undo action: {e}")

        print(f"\n✅ Undo complete: restored {reverted} file(s).")
        return reverted


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline AI File Organizer — supports any local or cloud LLM."
    )
    parser.add_argument("--folder", help="Folder path to organize")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--provider", help="LLM provider (lm_studio, ollama, openai, openrouter, anthropic, gemini, llama_cpp, openai_compatible)")
    parser.add_argument("--base-url", help="Custom OpenAI-compatible base URL")
    parser.add_argument("--model", help="Model name (or 'auto' for local detection)")
    parser.add_argument("--api-key", help="API key (prefer env vars)")
    parser.add_argument("--rename", action="store_true", help="Rename files")
    parser.add_argument("--organize", action="store_true", help="Organize files into category folders")
    parser.add_argument("--profile", choices=["simple", "smart", "custom"], help="Folder layout: smart uses up to two approved levels")
    parser.add_argument("--naming-template", help="Filename template with {title}, {date}, {category}")
    parser.add_argument("--include-images", action="store_true", help="Include PNG/JPG/WEBP images via Vision LLM or OCR")
    parser.add_argument("--save-plan", metavar="PLAN_FILE", help="Save dry-run plan to a JSON file and exit")
    parser.add_argument("--apply-plan", metavar="PLAN_FILE", help="Apply a previously saved plan JSON file")
    parser.add_argument("--yes", action="store_true", help="Apply changes without interactive confirmation")
    parser.add_argument("--watch", action="store_true", help="Continuously watch --folder for new or changed files")
    parser.add_argument("--workers", type=int, help="Maximum parallel file-analysis workers (watch mode)")
    parser.add_argument("--stability-delay", type=float, help="Seconds a file must remain unchanged before analysis (watch mode)")
    parser.add_argument("--auto-apply", action="store_true", help="Automatically move watched files; otherwise save a review plan")
    parser.add_argument("--undo", metavar="LOG_FILE", help="Undo changes from a saved organization_log_*.json file")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None):
    args = parse_args(argv)

    if args.undo:
        FileOrganizer.undo_from_log(args.undo)
        return

    cfg = load_config(args.config)
    if args.provider:
        cfg["llm"]["provider"] = args.provider
    if args.base_url:
        cfg["llm"]["base_url"] = args.base_url
    if args.model:
        cfg["llm"]["model"] = args.model
    if args.api_key:
        cfg["llm"]["api_key"] = args.api_key
    if args.include_images:
        cfg["organizer"]["enable_images"] = True
    if args.profile:
        cfg["organizer"]["profile"] = args.profile
    if args.naming_template:
        cfg["organizer"]["naming_template"] = args.naming_template

    if args.auto_apply and not args.watch:
        raise SystemExit("--auto-apply can only be used together with --watch.")
    if args.workers is not None and args.workers < 1:
        raise SystemExit("--workers must be at least 1.")
    if args.stability_delay is not None and args.stability_delay < 0:
        raise SystemExit("--stability-delay cannot be negative.")

    if args.apply_plan:
        with open(args.apply_plan, "r", encoding="utf-8") as f:
            plan_data = json.load(f)
        root = args.folder or plan_data.get("root_folder", ".")
        organizer = FileOrganizer(root, config=cfg)
        organizer.load_plan(args.apply_plan)
        organizer.apply_plan(save_log=True)
        return

    print(
        """
╔══════════════════════════════════════════════════════════╗
║     Offline AI-POWERED FILE ORGANIZER AND RENAMER        ║
║     Universal LLM Support (Local & Cloud)                ║
╚══════════════════════════════════════════════════════════╝
        """
    )

    if args.watch and not args.folder:
        raise SystemExit("Watch mode requires --folder PATH.")
    folder_path = args.folder or input("Enter the folder path to organize: ").strip('"')
    if not os.path.exists(folder_path):
        print("❌ Folder does not exist!")
        return

    if args.rename or args.organize:
        rename = args.rename
        organize = args.organize
    elif args.watch:
        rename = True
        organize = True
    else:
        print("\nOptions:")
        print("1. Rename files only")
        print("2. Organize files only")
        print("3. Both rename and organize")
        choice = input("Choose (1/2/3): ").strip()
        rename = choice in ("1", "3")
        organize = choice in ("2", "3")

    organizer = FileOrganizer(folder_path, config=cfg)

    print(f"\nTesting LLM connection ({organizer.llm.provider})...")
    ok, msg = organizer.llm.test_connection()
    if not ok:
        print(f"✗ {msg}")
        return
    print(f"✓ {msg}")

    if args.watch:
        from watch_folder import run_watch_mode

        watch_cfg = cfg["organizer"]
        workers = args.workers if args.workers is not None else int(watch_cfg.get("watch_workers", 2))
        stability_delay = (
            args.stability_delay
            if args.stability_delay is not None
            else float(watch_cfg.get("watch_stability_seconds", 1.5))
        )
        run_watch_mode(
            organizer,
            rename=rename,
            organize=organize,
            workers=workers,
            stability_seconds=stability_delay,
            auto_apply=args.auto_apply,
        )
        return

    print("\n⚠️  Building DRY RUN plan (no files will be modified yet)...")
    plan = organizer.build_plan(rename=rename, organize=organize)
    if not plan:
        print("\nNo changes planned.")
        return

    if args.save_plan:
        organizer.save_plan(args.save_plan)
        return

    proceed = "yes" if args.yes else input("\nApply these exact changes? (yes/no): ").strip().lower()
    if proceed == "yes":
        print("\n🚀 Applying exact cached plan...")
        organizer.apply_plan(save_log=True)
        print("\n✅ Done!")
    else:
        print("\n❌ Cancelled")


if __name__ == "__main__":
    main()
