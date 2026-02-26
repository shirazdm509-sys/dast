"""
ingestion.py - سیستم پردازش و ذخیره‌سازی رساله آیت‌الله دستغیب
ویژگی‌ها:
- استخراج دقیق مسائل با شماره واقعی از متن
- ذخیره section_path کامل برای هر مسئله
- embedding با مدل text-embedding-3-large
- پشتیبانی کامل از فارسی، عربی، اعداد
- context enrichment: section header + مسئله قبلی
"""

import os
import re
import json
import logging
import fitz
import docx
import chromadb
from openai import OpenAI
from typing import List, Dict
from datetime import datetime, timezone

logger = logging.getLogger("resaleh.ingestion")

CHROMA_PATH = os.environ.get("CHROMA_PATH", "./chroma_db")
COLLECTION_NAME = "resaleh_dastgheib"

API_KEY = os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable is required")
openai_client = OpenAI(api_key=API_KEY)


# ── ChromaDB ─────────────────────────────────────────────────
def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """text-embedding-3-large - بهترین مدل برای فارسی/عربی"""
    response = openai_client.embeddings.create(
        model="text-embedding-3-large",
        input=texts
    )
    return [item.embedding for item in response.data]


# ── نرمال‌سازی پیشرفته فارسی/عربی ───────────────────────────
def normalize(text: str) -> str:
    if not text:
        return ""
    char_map = {
        # یکسان‌سازی حروف عربی/فارسی
        'ك': 'ک', 'ي': 'ی', 'ة': 'ه', 'ؤ': 'و',
        'إ': 'ا', 'أ': 'ا', 'ئ': 'ی', 'ٱ': 'ا',
        # حذف کاراکترهای invisible
        '\u200c': ' ', '\u200d': '', '\u200e': '', '\u200f': '',
        '\u00ad': '', '\ufeff': '',
        # تبدیل اعداد فارسی/عربی به لاتین
        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
        '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
        '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
        '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
    }
    for k, v in char_map.items():
        text = text.replace(k, v)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_keywords(text: str) -> List[str]:
    stopwords = {
        'است', 'بود', 'شود', 'دارد', 'براى', 'برای', 'این', 'که', 'با',
        'از', 'در', 'به', 'را', 'هم', 'هر', 'یک', 'يک', 'اگر', 'نیست',
        'كند', 'کند', 'کرد', 'نماید', 'آن', 'اين', 'يا', 'مى', 'مي',
        'بايد', 'ولى', 'ولی', 'چنانچه', 'نيز', 'بلکه', 'بلكه', 'مثل',
        'همچنين', 'همچنین', 'بنابر', 'اگرچه', 'هنگامى', 'وقتى'
    }
    words = re.findall(r'[آ-ی]{3,}', text)
    freq = {}
    for w in words:
        if w not in stopwords:
            freq[w] = freq.get(w, 0) + 1
    return sorted(freq, key=freq.get, reverse=True)[:15]


# ── استخراج شماره واقعی مسئله از متن ────────────────────────
def extract_actual_problem_number(text: str, fallback_counter: int) -> int:
    """
    استخراج شماره واقعی مسئله از متن پاراگراف.
    مثل: 'مسأله 156 -' یا 'مسئله ۱۵۶'
    """
    patterns = [
        r'^(?:مسئله|مسأله|مساله)\s*[:\-–—]?\s*(\d+)',
        r'^(\d+)\s*[-\.–—]\s',
        r'(?:مسئله|مسأله|مساله)\s+(\d+)',
    ]
    for p in patterns:
        m = re.search(p, text.strip())
        if m:
            return int(m.group(1))
    return fallback_counter


# ── استخراج دقیق از Word با style-aware parsing ──────────────
def extract_word(file_path: str) -> List[Dict]:
    """
    استخراج با توجه به ساختار دقیق رساله دستغیب:
    - Heading 1: بخش اصلی (احکام تقلید، احکام طهارت، ...)
    - Heading 2: زیربخش (آب کر، مبطلات روزه، ...)
    - Heading 3/4/5: زیرزیربخش
    - 'مساله ها': هر پاراگراف = یک مسئله مستقل
    - Normal: احادیث و توضیحات
    """
    doc_obj = docx.Document(file_path)
    source = os.path.basename(file_path)
    chunks = []
    h1 = h2 = h3 = h4 = ""
    counter = 0

    for para in doc_obj.paragraphs:
        raw = para.text.strip()
        text = normalize(raw)
        style = para.style.name
        if not text:
            continue

        if style == 'Heading 1':
            h1 = text; h2 = h3 = h4 = ""; continue
        if style == 'Heading 2':
            h2 = text; h3 = h4 = ""; continue
        if style == 'Heading 3':
            h3 = text; h4 = ""; continue
        if style in ('Heading 4', 'Heading 5'):
            h4 = text; continue

        section_path = " > ".join(filter(None, [h1, h2, h3, h4]))

        if style == 'مساله ها':
            counter += 1
            # استخراج شماره واقعی از متن به جای شمارنده ترتیبی
            actual_number = extract_actual_problem_number(text, counter)
            kws = extract_keywords(text)

            # context enrichment: اضافه کردن header بخش
            section_context = f"بخش: {section_path}\n" if section_path else ""

            # اضافه کردن خلاصه مسئله قبلی برای context بهتر
            prev_context = ""
            if chunks and chunks[-1].get("chunk_type") == "masaleh":
                prev_summary = chunks[-1]["raw_text"][:100]
                prev_context = f"مسئله قبلی: {prev_summary}...\n"

            searchable = (
                f"مسئله {actual_number} | {section_context}"
                f"{prev_context}"
                f"متن مسئله: {text}"
            )

            chunks.append({
                "text": searchable,
                "raw_text": text,
                "source": source,
                "problem_number": actual_number,
                "section": h1,
                "subsection": h2,
                "sub2": h3,
                "section_path": section_path,
                "keywords": ",".join(kws),
                "chunk_type": "masaleh"
            })

        elif style == 'Normal' and len(text) > 40:
            kws = extract_keywords(text)
            chunks.append({
                "text": f"توضیح | بخش: {section_path}\n{text}",
                "raw_text": text,
                "source": source,
                "problem_number": -1,
                "section": h1,
                "subsection": h2,
                "sub2": h3,
                "section_path": section_path,
                "keywords": ",".join(kws),
                "chunk_type": "normal"
            })

    logger.info(f"Extracted {len(chunks)} chunks from {source}")
    return chunks


def extract_pdf(file_path: str) -> List[Dict]:
    doc = fitz.open(file_path)
    source = os.path.basename(file_path)
    chunks = []
    counter = 0
    for page_num in range(len(doc)):
        text = normalize(doc[page_num].get_text("text"))
        for para in [p.strip() for p in text.split('\n\n') if len(p.strip()) > 30]:
            counter += 1
            kws = extract_keywords(para)
            chunks.append({
                "text": f"مسئله {counter} | صفحه {page_num+1}\n{para}",
                "raw_text": para,
                "source": source,
                "problem_number": counter,
                "section": f"صفحه {page_num+1}",
                "subsection": "", "sub2": "",
                "section_path": f"صفحه {page_num+1}",
                "keywords": ",".join(kws),
                "chunk_type": "pdf"
            })
    doc.close()
    logger.info(f"Extracted {len(chunks)} chunks from {source} (PDF)")
    return chunks


# ── Pipeline اصلی ────────────────────────────────────────────
def ingest_file(file_path: str, filename: str) -> Dict:
    logger.info(f"Processing: {filename}")
    print(f"\n{'='*50}")
    print(f"Processing: {filename}")
    print(f"{'='*50}")

    if filename.lower().endswith('.pdf'):
        chunks = extract_pdf(file_path)
    elif filename.lower().endswith(('.docx', '.doc')):
        chunks = extract_word(file_path)
    else:
        raise ValueError(f"Unsupported: {filename}")

    if not chunks:
        raise ValueError("No content extracted")

    masaleh = [c for c in chunks if c["chunk_type"] == "masaleh"]
    sections = list(dict.fromkeys(c["section"] for c in chunks if c["section"]))

    print(f"Total chunks: {len(chunks)}")
    print(f"Masaleh: {len(masaleh)}")
    print(f"Sections ({len(sections)}): {sections[:5]}")

    collection = get_collection()

    # حذف قدیمی
    try:
        ex = collection.get(where={"source": filename})
        if ex["ids"]:
            collection.delete(ids=ex["ids"])
            print(f"Removed {len(ex['ids'])} old chunks")
    except Exception as e:
        logger.warning(f"Cleanup error: {e}")

    ids = [f"{filename}_{i}" for i in range(len(chunks))]
    documents = [c["text"] for c in chunks]
    metadatas = [{
        "source": c["source"],
        "page": 1,
        "chunk_index": i,
        "problem_number": c["problem_number"],
        "section": c["section"],
        "subsection": c["subsection"],
        "sub2": c.get("sub2", ""),
        "section_path": c["section_path"],
        "keywords": c["keywords"],
        "chunk_type": c["chunk_type"],
        "ingested_at": datetime.now(timezone.utc).isoformat()
    } for i, c in enumerate(chunks)]

    # embedding batch
    batch = 20
    for i in range(0, len(ids), batch):
        b_ids = ids[i:i+batch]
        b_docs = documents[i:i+batch]
        b_metas = metadatas[i:i+batch]
        b_embs = get_embeddings(b_docs)
        collection.add(ids=b_ids, documents=b_docs, metadatas=b_metas, embeddings=b_embs)
        pct = int((i + len(b_ids)) / len(ids) * 100)
        print(f"  [{pct:3d}%] Embedded {i+len(b_ids)}/{len(ids)}")

    save_file_info(filename, len(ids), len(chunks))
    logger.info(f"Ingestion complete: {filename} - {len(ids)} chunks")
    print(f"\n✓ Done! {len(ids)} chunks saved.")
    return {"chunks_added": len(ids), "pages_processed": len(chunks)}


# ── File info ────────────────────────────────────────────────
INFO_FILE = "./files_info.json"


def save_file_info(fn, chunks, pages):
    info = {}
    if os.path.exists(INFO_FILE):
        with open(INFO_FILE, encoding="utf-8") as f:
            info = json.load(f)
    info[fn] = {
        "chunks": chunks,
        "pages": pages,
        "uploaded_at": datetime.now(timezone.utc).isoformat()
    }
    with open(INFO_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)


def get_ingested_files():
    if not os.path.exists(INFO_FILE):
        return []
    with open(INFO_FILE, encoding="utf-8") as f:
        info = json.load(f)
    return [{"filename": k, **v} for k, v in info.items()]


def delete_file_chunks(filename):
    collection = get_collection()
    try:
        ex = collection.get(where={"source": filename})
        if ex["ids"]:
            collection.delete(ids=ex["ids"])
        if os.path.exists(INFO_FILE):
            with open(INFO_FILE, encoding="utf-8") as f:
                info = json.load(f)
            info.pop(filename, None)
            with open(INFO_FILE, "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
        return {"success": True, "message": f"{filename} deleted"}
    except Exception as e:
        logger.error(f"Delete file chunks error: {e}")
        return {"success": False, "message": str(e)}


def get_collection_stats():
    try:
        col = get_collection()
        files = get_ingested_files()
        return {"total_chunks": col.count(), "total_files": len(files), "files": files}
    except Exception as e:
        logger.error(f"Collection stats error: {e}")
        return {"total_chunks": 0, "total_files": 0, "files": [], "error": str(e)}
