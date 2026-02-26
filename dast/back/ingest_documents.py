"""
ingest_documents.py - پردازش فایل‌های رساله
فقط از طریق ترمینال توسط ادمین اجرا شود

نیاز به تنظیم متغیر محیطی OPENAI_API_KEY قبل از اجرا:
  export OPENAI_API_KEY=sk-your-key-here
  python ingest_documents.py
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
from ingestion import ingest_file, get_collection_stats

DOCS_DIR = os.environ.get("DOCS_DIR", "/opt/resaleh/documents")
os.makedirs(DOCS_DIR, exist_ok=True)


def main():
    # بررسی API key
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable is not set!")
        print("  export OPENAI_API_KEY=sk-your-key-here")
        sys.exit(1)

    files = [f for f in os.listdir(DOCS_DIR) if f.lower().endswith(('.pdf', '.docx', '.doc'))]
    if not files:
        print(f"No files found in {DOCS_DIR}")
        return

    print(f"Found {len(files)} file(s)...")
    for fn in files:
        fp = os.path.join(DOCS_DIR, fn)
        print(f"\nProcessing: {fn}")
        try:
            r = ingest_file(fp, fn)
            print(f"  Done: {r['chunks_added']} chunks")
        except Exception as e:
            print(f"  Error: {e}")

    print("\n" + "=" * 40)
    st = get_collection_stats()
    print(f"Total: {st['total_chunks']} chunks | {st['total_files']} files")


if __name__ == "__main__":
    main()
