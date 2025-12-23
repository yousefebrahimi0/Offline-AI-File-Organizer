"""
Offline AI-Powered File Organizer and Renamer
Uses LM Studio (local AI) to intelligently rename and organize files
Supports only: PDF, DOC, DOCX, TXT, EPUB, CSV, XLSX, XLS, RTF, ODT, MD
"""

import os
import re
import shutil
import mimetypes
from pathlib import Path
from datetime import datetime
import requests
import json

# Document extraction libraries
try:
    import PyPDF2
    import docx
    import openpyxl
    import pandas as pd
    import ebooklib
    from ebooklib import epub
except ImportError:
    print("Installing required libraries...")
    print("Please run: pip install PyPDF2 python-docx openpyxl pandas ebooklib")
    exit(1)

# Configuration
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
SUPPORTED_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.txt', '.epub', '.csv', 
    '.xlsx', '.xls', '.rtf', '.odt', '.md'
}
MAX_CONTENT_LENGTH = 3000  # Characters to send to AI

class FileOrganizer:
    def __init__(self, root_folder):
        self.root_folder = Path(root_folder)
        self.rename_log = []
        self.organize_log = []
        
    def extract_text_content(self, file_path):
        """Extract text content from various file types"""
        ext = file_path.suffix.lower()
        content = ""
        
        try:
            if ext == '.pdf':
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    for page in pdf_reader.pages[:3]:  # First 3 pages
                        content += page.extract_text() + " "
            
            elif ext == '.docx':
                doc = docx.Document(file_path)
                content = " ".join([para.text for para in doc.paragraphs[:20]])
            
            elif ext == '.txt' or ext == '.md':
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(MAX_CONTENT_LENGTH)
            
            elif ext in ['.csv']:
                df = pd.read_csv(file_path, nrows=10)
                content = f"CSV with columns: {', '.join(df.columns.tolist())}\n"
                content += df.head(5).to_string()
            
            elif ext in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path, nrows=10)
                content = f"Excel with columns: {', '.join(df.columns.tolist())}\n"
                content += df.head(5).to_string()
            
            elif ext == '.epub':
                book = epub.read_epub(str(file_path))
                title = book.get_metadata('DC', 'title')
                content = f"EPUB Book: {title[0][0] if title else 'Unknown'}"
            
        except Exception as e:
            print(f"Error extracting content from {file_path.name}: {e}")
            content = f"File: {file_path.stem}"
        
        return content[:MAX_CONTENT_LENGTH]
    
    def ask_ai_for_name(self, filename, content, file_date):
        """Ask local AI for a descriptive filename"""
        prompt = f"""You are a file naming assistant. Given the content of a document, suggest a clear, descriptive filename.

Rules:
- Use only alphanumeric characters, spaces, hyphens, and underscores
- Maximum 60 characters
- Be specific and descriptive
- Use title case
- Include relevant year/month if important (e.g., for reports, invoices)
- NO file extension in your response

Original filename: {filename}
File date: {file_date}
Content preview:
{content[:1000]}

Respond with ONLY the new filename, nothing else."""

        try:
            response = requests.post(
                LM_STUDIO_URL,
                json={
                    "model": "mistral-7b-instruct",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 50
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                new_name = result['choices'][0]['message']['content'].strip()
                # Clean the filename
                new_name = re.sub(r'[<>:"/\\|?*]', '', new_name)
                new_name = re.sub(r'\s+', ' ', new_name)
                new_name = new_name[:60].strip()
                return new_name
            else:
                print(f"AI request failed: {response.status_code}")
                return None
        except Exception as e:
            print(f"Error connecting to LM Studio: {e}")
            return None
    
    def ask_ai_for_category(self, filename, content):
        """Ask AI to categorize the file"""
        prompt = f"""Categorize this document into ONE category.

Choose from: Work, Personal, Finance, Medical, Education, Legal, Photos, Projects, Archive, Miscellaneous

Content preview:
{content[:800]}

Respond with ONLY the category name, nothing else."""

        try:
            response = requests.post(
                LM_STUDIO_URL,
                json={
                    "model": "mistral-7b-instruct",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 10
                },
                timeout=20
            )
            
            if response.status_code == 200:
                result = response.json()
                category = result['choices'][0]['message']['content'].strip()
                return category
            else:
                return "Miscellaneous"
        except Exception as e:
            return "Miscellaneous"
    
    def get_file_date_string(self, file_path):
        """Get file modification date as string"""
        timestamp = os.path.getmtime(file_path)
        date = datetime.fromtimestamp(timestamp)
        return date.strftime("%Y-%m")
    
    def sanitize_filename(self, name):
        """Ensure filename is safe for Windows"""
        # Remove invalid characters
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        # Remove leading/trailing spaces and dots
        name = name.strip('. ')
        # Limit length
        return name[:200]
    
    def rename_file(self, file_path, dry_run=True):
        """Rename a single file using AI"""
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return None
        
        print(f"\nProcessing: {file_path.name}")
        
        # Extract content
        content = self.extract_text_content(file_path)
        file_date = self.get_file_date_string(file_path)
        
        # Get AI suggestion
        new_name = self.ask_ai_for_name(file_path.stem, content, file_date)
        
        if not new_name:
            print(f"  ⚠️  Could not generate name, skipping")
            return None
        
        # Add date suffix and extension
        new_filename = f"{new_name} ({file_date}){file_path.suffix}"
        new_filename = self.sanitize_filename(new_filename)
        new_path = file_path.parent / new_filename
        
        # Handle duplicates
        counter = 1
        while new_path.exists() and new_path != file_path:
            new_filename = f"{new_name} ({file_date}) [{counter}]{file_path.suffix}"
            new_path = file_path.parent / new_filename
            counter += 1
        
        print(f"  ✓ Suggested: {new_filename}")
        
        if not dry_run and new_path != file_path:
            try:
                file_path.rename(new_path)
                self.rename_log.append({
                    'old': str(file_path),
                    'new': str(new_path)
                })
                return new_path
            except Exception as e:
                print(f"  ✗ Error renaming: {e}")
                return None
        
        return new_path
    
    def organize_files(self, organize_root, dry_run=True):
        """Organize files into categorized folders"""
        print("\n" + "="*60)
        print("ORGANIZING FILES BY CATEGORY")
        print("="*60)
        
        all_files = []
        for file_path in self.root_folder.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                all_files.append(file_path)
        
        print(f"\nFound {len(all_files)} files to organize")
        
        for file_path in all_files:
            content = self.extract_text_content(file_path)
            category = self.ask_ai_for_category(file_path.name, content)
            
            # Create category folder
            category_folder = Path(organize_root) / category
            
            if not dry_run:
                category_folder.mkdir(parents=True, exist_ok=True)
                
                # Move file
                new_path = category_folder / file_path.name
                counter = 1
                while new_path.exists():
                    new_path = category_folder / f"{file_path.stem} [{counter}]{file_path.suffix}"
                    counter += 1
                
                try:
                    shutil.move(str(file_path), str(new_path))
                    print(f"  ✓ Moved to {category}: {file_path.name}")
                    self.organize_log.append({
                        'file': file_path.name,
                        'from': str(file_path.parent),
                        'to': str(new_path.parent)
                    })
                except Exception as e:
                    print(f"  ✗ Error moving {file_path.name}: {e}")
            else:
                print(f"  → Would move to {category}: {file_path.name}")
    
    def process_all_files(self, rename=True, organize=False, dry_run=True):
        """Process all files in the folder"""
        print("\n" + "="*60)
        print(f"AI FILE ORGANIZER - {'DRY RUN' if dry_run else 'LIVE MODE'}")
        print("="*60)
        print(f"Root folder: {self.root_folder}")
        print(f"Rename files: {rename}")
        print(f"Organize files: {organize}")
        
        # Test LM Studio connection
        print("\nTesting LM Studio connection...")
        try:
            test_response = requests.get("http://localhost:1234/v1/models", timeout=5)
            if test_response.status_code == 200:
                print("✓ LM Studio is running")
            else:
                print("✗ LM Studio connection failed")
                return
        except:
            print("✗ Cannot connect to LM Studio. Make sure it's running on port 1234")
            return
        
        # Collect all files
        all_files = []
        for file_path in self.root_folder.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                all_files.append(file_path)
        
        print(f"\nFound {len(all_files)} supported files")
        
        if rename:
            print("\n" + "="*60)
            print("RENAMING FILES")
            print("="*60)
            
            for file_path in all_files:
                self.rename_file(file_path, dry_run)
        
        if organize:
            organize_root = self.root_folder / "Organized"
            self.organize_files(organize_root, dry_run)
        
        # Save log
        if not dry_run:
            log_file = self.root_folder / f"organization_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(log_file, 'w') as f:
                json.dump({
                    'renamed': self.rename_log,
                    'organized': self.organize_log
                }, f, indent=2)
            print(f"\n✓ Log saved to: {log_file}")


def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║     Offline AI-POWERED FILE ORGANIZER AND RENAMER               ║
║     Uses Local LM Studio (Mistral-7B)                   ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    # Get folder path
    folder_path = input("Enter the folder path to organize: ").strip('"')
    
    if not os.path.exists(folder_path):
        print("❌ Folder does not exist!")
        return
    
    # Options
    print("\nOptions:")
    print("1. Rename files only")
    print("2. Organize files only")
    print("3. Both rename and organize")
    choice = input("Choose (1/2/3): ").strip()
    
    rename = choice in ['1', '3']
    organize = choice in ['2', '3']
    
    # Dry run first
    print("\n⚠️  Running in DRY RUN mode first (no changes will be made)")
    input("Press Enter to continue...")
    
    organizer = FileOrganizer(folder_path)
    organizer.process_all_files(rename=rename, organize=organize, dry_run=True)
    
    # Confirm
    print("\n" + "="*60)
    proceed = input("\nApply these changes? (yes/no): ").strip().lower()
    
    if proceed == 'yes':
        print("\n🚀 Applying changes...")
        organizer = FileOrganizer(folder_path)
        organizer.process_all_files(rename=rename, organize=organize, dry_run=False)
        print("\n✅ Done!")
    else:
        print("\n❌ Cancelled")


if __name__ == "__main__":
    main()