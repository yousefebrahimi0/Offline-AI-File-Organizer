"""
Offline AI-Powered File Organizer and Renamer by Yousef; https://github.com/yousefebrahimi0/
Uses any local or cloud LLM (LM Studio, Ollama, llama.cpp, OpenAI, OpenRouter, Anthropic, Gemini)
to intelligently rename and organize files with dry-run plan caching and one-click undo.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

# Optional document extraction libraries (graceful fallback per format)
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


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".epub",
    ".csv",
    ".xlsx",
    ".xls",
    ".md",
}

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
            "max_tokens": 120,
            "timeout": 45,
        },
        "organizer": {
            "max_content_length": 3000,
            "organize_folder_name": "Organized",
            "ignore_folders": [
                "Organized",
                ".git",
                "__pycache__",
                "node_modules",
                ".venv",
                "venv",
            ],
            "categories": list(DEFAULT_CATEGORIES),
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
    ):
        self.provider = (provider or "lm_studio").lower().strip()
        preset = PROVIDER_DEFAULTS.get(self.provider, PROVIDER_DEFAULTS["openai_compatible"])
        self.api_type = preset["api_type"]
        self.base_url = (base_url or preset["base_url"]).rstrip("/")
        self.model = model or "auto"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

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

    def chat(self, prompt: str) -> Optional[str]:
        """Send a single-turn user prompt and return the text response."""
        try:
            if self.api_type == "openai":
                url = (
                    self.base_url
                    if self.base_url.endswith("/chat/completions")
                    else f"{self.base_url}/chat/completions"
                )
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
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
                payload = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "messages": [{"role": "user", "content": prompt}],
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
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": self.temperature,
                        "maxOutputTokens": self.max_tokens,
                    },
                }
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    candidates = resp.json().get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        return "".join(p.get("text", "") for p in parts).strip()
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
        self.ignore_folders = set(org_cfg.get("ignore_folders", ["Organized", ".git"]))
        self.ignore_folders.add(self.organize_folder_name)
        self.categories = list(org_cfg.get("categories", DEFAULT_CATEGORIES))

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
            )

        self.planned_actions: List[Dict[str, str]] = []
        self.executed_log: List[Dict[str, str]] = []

    def _is_ignored(self, file_path: Path) -> bool:
        """Skip files inside Organized/ or other ignored directories."""
        try:
            rel_parts = file_path.relative_to(self.root_folder).parts[:-1]
        except ValueError:
            rel_parts = file_path.parts[:-1]
        return any(part in self.ignore_folders for part in rel_parts)

    def discover_files(self) -> List[Path]:
        """Find all supported files while excluding ignored directories."""
        files = []
        for file_path in sorted(self.root_folder.rglob("*")):
            if (
                file_path.is_file()
                and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
                and not self._is_ignored(file_path)
            ):
                files.append(file_path)
        return files

    def extract_text_content(self, file_path: Path) -> str:
        """Extract text content safely from supported file types."""
        ext = file_path.suffix.lower()
        content = ""

        try:
            if ext == ".pdf" and PdfReader is not None:
                with open(file_path, "rb") as f:
                    pdf_reader = PdfReader(f)
                    chunks = []
                    for page in pdf_reader.pages[:3]:
                        text = page.extract_text() or ""
                        if text:
                            chunks.append(text)
                    content = " ".join(chunks)

            elif ext == ".docx" and docx is not None:
                doc = docx.Document(file_path)
                content = " ".join(para.text for para in doc.paragraphs[:20] if para.text)

            elif ext in (".txt", ".md"):
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(self.max_content_length)

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

    def analyze_file(
        self, file_path: Path, rename: bool = True, organize: bool = True
    ) -> Tuple[Optional[str], str]:
        """Single-call structured JSON analysis for both filename and category."""
        content = self.extract_text_content(file_path)
        file_date = self.get_file_date_string(file_path)
        categories_str = ", ".join(self.categories)

        prompt = f"""You are a file organization assistant. Analyze the document below and respond with ONLY a valid JSON object.

JSON format:
{{"filename": "Descriptive Title Without Extension", "category": "OneCategory"}}

Rules:
- filename: clear, specific, max 60 chars, no file extension, title case (or Persian if content is Persian).
- category: MUST be one of [{categories_str}].

Original filename: {file_path.stem}
File date: {file_date}
Content preview:
{content[:1200]}"""

        raw = self.llm.chat(prompt)
        if not raw:
            return None, "Miscellaneous"

        parsed = self._parse_json_response(raw)
        suggested_name = None
        if rename and parsed.get("filename"):
            suggested_name = self.sanitize_filename(parsed["filename"], max_len=60)
        category = (
            self.sanitize_category(parsed.get("category", "Miscellaneous"))
            if organize
            else "Miscellaneous"
        )
        return suggested_name, category

    def build_plan(self, rename: bool = True, organize: bool = False) -> List[Dict[str, str]]:
        """Run dry-run analysis once and cache the exact planned operations."""
        self.planned_actions = []
        all_files = self.discover_files()
        print(f"\nFound {len(all_files)} supported files")

        reserved_targets = set()
        organize_root = self.root_folder / self.organize_folder_name

        for file_path in all_files:
            print(f"\nAnalyzing: {file_path.name}")
            file_date = self.get_file_date_string(file_path)
            suggested_name, category = self.analyze_file(
                file_path, rename=rename, organize=organize
            )

            target_dir = (organize_root / category) if organize else file_path.parent
            if rename and suggested_name:
                base_name = self.sanitize_filename(f"{suggested_name} ({file_date})", max_len=180)
                target_name = f"{base_name}{file_path.suffix}"
            else:
                target_name = file_path.name

            target_path = target_dir / target_name
            counter = 1
            while (
                (target_path.exists() and target_path != file_path)
                or str(target_path) in reserved_targets
            ):
                stem = Path(target_name).stem
                target_path = target_dir / f"{stem} [{counter}]{file_path.suffix}"
                counter += 1

            reserved_targets.add(str(target_path))

            if target_path == file_path:
                print("  • No change needed")
                continue

            action = {
                "old_path": str(file_path),
                "new_path": str(target_path),
                "category": category if organize else "",
            }
            self.planned_actions.append(action)
            rel_new = (
                target_path.relative_to(self.root_folder)
                if self.root_folder in target_path.parents
                else target_path
            )
            print(f"  → Planned: {file_path.name}  ==>  {rel_new}")

        return self.planned_actions

    def apply_plan(self, save_log: bool = True) -> Optional[Path]:
        """Execute the exact cached plan from build_plan() without re-querying the LLM."""
        self.executed_log = []
        for action in self.planned_actions:
            old_path = Path(action["old_path"])
            new_path = Path(action["new_path"])
            if not old_path.exists():
                print(f"  ⚠️  Skipped missing file: {old_path}")
                continue
            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(new_path))
                self.executed_log.append(action)
                print(f"  ✓ Applied: {old_path.name}  ==>  {new_path.name}")
            except Exception as e:
                print(f"  ✗ Error moving {old_path.name}: {e}")

        if save_log and self.executed_log:
            log_file = (
                self.root_folder
                / f"organization_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "version": 2,
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
        """Revert all renames and moves recorded in an organization_log_*.json file."""
        log_path = Path(log_file_path)
        if not log_path.exists():
            print(f"❌ Log file not found: {log_path}")
            return 0

        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        actions = data.get("actions", [])
        reverted = 0
        for action in reversed(actions):
            old_path = Path(action["old_path"])
            new_path = Path(action["new_path"])
            if new_path.exists():
                old_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(new_path), str(old_path))
                reverted += 1
                print(f"  ↩ Restored: {new_path.name}  ==>  {old_path}")
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
    parser.add_argument("--yes", action="store_true", help="Apply changes without interactive confirmation")
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

    print(
        """
╔══════════════════════════════════════════════════════════╗
║     Offline AI-POWERED FILE ORGANIZER AND RENAMER        ║
║     Universal LLM Support (Local & Cloud)                ║
╚══════════════════════════════════════════════════════════╝
        """
    )

    folder_path = args.folder or input("Enter the folder path to organize: ").strip('"')
    if not os.path.exists(folder_path):
        print("❌ Folder does not exist!")
        return

    if args.rename or args.organize:
        rename = args.rename
        organize = args.organize
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

    print("\n⚠️  Building DRY RUN plan (no files will be modified yet)...")
    plan = organizer.build_plan(rename=rename, organize=organize)
    if not plan:
        print("\nNo changes planned.")
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
