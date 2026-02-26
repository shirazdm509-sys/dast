"""
retriever.py - سیستم جستجو و پاسخ‌دهی رساله آیت‌الله دستغیب
ویژگی‌ها:
- درک سوالات عامیانه فارسی (حکم سیگار در رمضون چیه؟)
- جستجوی مستقیم شماره مسئله (مسیر سریع بدون API call اضافی)
- جستجوی semantic با چند query بهینه
- reranking هوشمند (فقط در صورت نیاز)
- ارائه رفرنس کامل (شماره مسئله + بخش)
- پشتیبانی چندزبانه (فارسی، عربی، انگلیسی)
- حافظه مکالمه برای سوالات پیگیری
"""

import os
import re
import json
import asyncio
import logging
from typing import List, Dict, Optional, AsyncGenerator
from openai import OpenAI, AsyncOpenAI
from ingestion import get_collection, get_collection_stats, get_embeddings
from session_memory import memory

logger = logging.getLogger("resaleh.retriever")

API_KEY = os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable is required")
client = OpenAI(api_key=API_KEY)
async_client = AsyncOpenAI(api_key=API_KEY)

SIMILARITY_THRESHOLD = 0.13

# ── نقشه section به شماره مسئله (از تحلیل فایل واقعی) ─────────
SECTION_PROBLEM_MAP = {
    "احکام تقلید": (1, 15),
    "احکام طهارت": (16, 83),
    "نجاسات": (84, 149),
    "مطهرات": (150, 236),
    "وضو": (237, 347),
    "غسل": (348, 530),
    "احکام میت": (531, 644),
    "تیمم": (645, 723),
    "احکام نماز": (724, 1620),
    "احکام روزه": (1621, 1818),
    "احکام خمس": (1819, 1921),
    "احکام زکات": (1922, 2104),
    "احکام حج": (2105, 2120),
    "احکام خرید و فروش": (2121, 2214),
    "احکام شرکت": (2215, 2240),
    "احکام صلح": (2241, 2260),
    "احکام اجاره": (2261, 2310),
    "احکام جعاله": (2311, 2320),
    "احکام مزارعه": (2321, 2340),
    "احکام مساقات": (2341, 2350),
    "احکام حجر و بلوغ": (2351, 2370),
    "احکام وکالت": (2371, 2390),
    "احکام قرض": (2391, 2410),
    "احکام حواله": (2411, 2420),
    "احکام رهن": (2421, 2435),
    "احکام ضامن شدن": (2436, 2451),
    "احکام نکاح": (2452, 2554),
    "احکام شیر دادن": (2555, 2588),
    "احکام طلاق": (2589, 2637),
    "احکام غصب": (2638, 2660),
    "احکام ارث": (2661, 2716),
    "احکام خوردنیها": (2717, 2732),
    "احکام نذر و عهد": (2733, 2780),
    "احکام قسم خوردن": (2781, 2800),
    "احکام وقف": (2801, 2860),
    "احکام وصیت": (2861, 2900),
    "امر به معروف و نهی از منکر": (2901, 2950),
}

# ── Small Talk ───────────────────────────────────────────────
SMALL_TALK = {
    "سلام": "سلام! خوش آمدید.\nمن دستیار رساله آیت‌الله سید علی محمد دستغیب هستم.\nسوال فقهی خود را بپرسید.",
    "خوبی": "ممنون! در خدمتم. چه سوالی دارید؟",
    "چطوری": "خوبم! آماده پاسخ به سوالات فقهی شما هستم.",
    "ممنون": "خواهش می‌کنم! اگر سوال دیگری دارید بفرمایید.",
    "مرسی": "خواهش می‌کنم!",
    "ممنونم": "خواهش می‌کنم! در خدمتم.",
    "خداحافظ": "خداحافظ! موفق باشید.",
    "بای": "خداحافظ!",
    "hello": "سلام! چه سوالی از رساله دارید؟",
    "hi": "سلام!",
    "کی هستی": "من دستیار رساله فقهی آیت‌الله سید علی محمد دستغیب هستم و سوالات فقهی را از رساله ایشان پاسخ می‌دهم.",
    "چی میدونی": "رساله کامل آیت‌الله دستغیب را می‌دانم: از احکام طهارت، نماز، روزه، خمس، زکات تا احکام معاملات، ازدواج، طلاق و امر به معروف.",
    "چه بلدی": "رساله کامل آیت‌الله دستغیب را می‌دانم. هر سوال فقهی که دارید بپرسید.",
}


def is_small_talk(q: str) -> Optional[str]:
    q_lower = q.strip().lower()
    if len(q_lower) > 70:
        return None
    for k, v in SMALL_TALK.items():
        if k in q_lower:
            return v
    return None


# ── نرمال‌سازی سوالات عامیانه فارسی ─────────────────────────
COLLOQUIAL_FIXES = {
    # تلفظ عامیانه ← رسمی
    "رمضون": "رمضان",
    "ماه رمضون": "ماه رمضان",
    "نمازخوندن": "نماز خواندن",
    "نماز خوندن": "نماز خواندن",
    "وضوگرفتن": "وضو گرفتن",
    "وضو گرفتن": "وضو گرفتن",
    "دستشویی": "تخلی",
    "توالت": "تخلی",
    "عروسی": "ازدواج نکاح",
    # کلمات عامیانه ← فقهی
    "سیگار کشیدن": "سیگار دود دخان تنباکو",
    "سیگار کشیدن در": "دود سیگار تنباکو در",
    "قلیان کشیدن": "قلیان دود دخان",
    "ناپاک": "نجس",
    "پاک کردن": "تطهیر",
    "گناهه": "حرام است",
    "گناه داره": "حرام است",
    "چی میشه": "حکم چیست",
    "چیه حکمش": "حکم چیست",
    "حکمش چیه": "حکم چیست",
    "مشکلی داره": "جایز است یا خیر",
    "میشه": "جایز است",
    "نمیشه": "جایز نیست",
    "میتونم": "می‌توانم",
    "میتوانم": "می‌توانم",
    "چیه": "چیست",
    "کجاست": "کجاست",
    "باطله": "باطل است",
    "صحیحه": "صحیح است",
    # مایعات بدن
    "آب آلت": "منی مذی",
    "آبی که از آلت": "منی مذی",
    "آب مرد": "منی",
    "ریختن": "خروج",
    "ریخته": "خارج شده",
    "ریخته بشه": "خارج شود",
    "بریزه": "خارج شود",
    # فعل‌های عامیانه
    "خوردم": "خوردن",
    "بخورم": "خوردن",
    "بزنم": "زدن",
    "برم": "رفتن",
    "بیام": "آمدن",
    "بشینم": "نشستن",
    # کلمات عامیانه دیگر
    "حالا": "اکنون",
    "الان": "اکنون",
    "واسه": "برای",
    "بخاطر": "به خاطر",
    "اشکال داره": "اشکال دارد",
    "فرق داره": "تفاوت دارد",
    # اصطلاحات مذهبی عامیانه
    "آبدست": "وضو",
    "غسل کردن": "غسل",
}

# مترادف‌های فقهی - اضافه به query برای جستجوی بهتر
FIQH_EXPAND = {
    "سیگار": "دود سیگار دخان تنباکو",
    "قلیان": "قلیان دود دخان",
    "روزه": "روزه صوم صائم",
    "رمضان": "رمضان ماه رمضان",
    "نماز": "نماز صلات",
    "وضو": "وضو طهارت",
    "غسل": "غسل جنابت",
    "نجس": "نجس نجاست",
    "پاک": "طاهر طهارت",
    "خون": "خون دم",
    "نفاس": "خون نفاس",
    "حیض": "حیض خون حیض",
    "جنب": "جنابت جنب",
    "ازدواج": "نکاح ازدواج عقد",
    "طلاق": "طلاق فسخ",
    "خرید": "بیع معامله خرید و فروش",
    "ربا": "ربا بهره سود",
    "خمس": "خمس",
    "زکات": "زکات",
    "حج": "حج",
    "منی": "منی مذی وذی جنابت",
    "مذی": "مذی وذی",
    "استحاضه": "استحاضه خون استحاضه",
    "میت": "میت مرده جنازه",
    "تیمم": "تیمم بدل وضو بدل غسل",
    "شک": "شک شکیات",
    "سجده": "سجده سجود",
    "رکوع": "رکوع",
    "قبله": "قبله استقبال",
    "حرام": "حرام محرمات",
    "مکروه": "مکروه مکروهات",
    "واجب": "واجب واجبات فرض",
    "مستحب": "مستحب مستحبات",
}


def normalize_colloquial(q: str) -> str:
    """تبدیل سوال عامیانه به رسمی"""
    result = q
    for coll, formal in COLLOQUIAL_FIXES.items():
        result = result.replace(coll, formal)
    result = re.sub(r'[؟?!]+', '؟', result)
    return result.strip()


def expand_query(q: str) -> str:
    """اضافه کردن مترادف‌های فقهی به query"""
    expansions = []
    for word, synonyms in FIQH_EXPAND.items():
        if word in q:
            expansions.append(synonyms)
    if expansions:
        return q + " " + " ".join(expansions)
    return q


# ── تشخیص زبان ──────────────────────────────────────────────
def detect_language(question: str) -> str:
    """تشخیص زبان سوال بدون API call"""
    persian_chars = len(re.findall(r'[\u0600-\u06FF]', question))
    english_chars = len(re.findall(r'[a-zA-Z]', question))

    if english_chars > persian_chars:
        return "en"
    if re.search(r'[پچژگ]', question):
        return "fa"
    if persian_chars > 0:
        return "fa"
    return "en"


ANSWER_IN_LANGUAGE_ADDENDUM = {
    "en": "\n\nIMPORTANT: Provide your answer in English. Transliterate key Farsi terms.",
    "ar": "\n\nمهم: أجب باللغة العربية. مع ذکر المصطلحات الفقهية.",
    "fa": "",
}


def translate_to_farsi(question: str, lang: str) -> str:
    """ترجمه سوال به فارسی برای جستجو"""
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Translate this {lang} question about Islamic jurisprudence to Farsi. Keep Islamic terminology accurate.\nQuestion: {question}\nFarsi translation:"
            }],
            temperature=0,
            max_tokens=200
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Translation error: {e}")
        return question


# ── تشخیص شماره مسئله ────────────────────────────────────────
def extract_problem_number(q: str) -> Optional[int]:
    patterns = [
        r'(?:مسئله|مسأله|مساله|سوال)\s*(\d+)',
        r'(\d+)\s*(?:ام|مین)?\s*(?:مسئله|مسأله)',
        r'^(\d+)\s*[-\.\)]\s',
        r'(?:masaleh|masale|question)\s*#?\s*(\d+)',
    ]
    for p in patterns:
        m = re.search(p, q, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


# ── تحلیل سوال با GPT-4o ─────────────────────────────────────
def analyze_question(original: str, normalized: str) -> Dict:
    prompt = f"""تو متخصص فقه اسلامی و رساله‌های عملیه هستی.
سوال فارسی (ممکن است عامیانه باشد) درباره رساله فقهی دریافت کن و JSON برگردان:

{{
  "keywords_fa": ["کلمات کلیدی فقهی فارسی - حداکثر 8 تا"],
  "keywords_ar": ["مترادف عربی فقهی"],
  "section": "بخش رساله که جواب احتمالاً در آن است (مثل: احکام روزه)",
  "formal_query": "سوال به فارسی فقهی رسمی و کامل",
  "keyword_query": "فقط کلمات کلیدی فقهی بدون فعل و کمک‌فعل",
  "expanded_query": "سوال با توضیحات و مترادف‌های فقهی بیشتر",
  "is_about_prohibition": true/false
}}

مهم:
- "سیگار در رمضون" → formal: "حکم دود سیگار و دخان برای روزه‌دار در ماه رمضان"
- "میشه نماز خوند" → formal: "آیا نماز خواندن در این شرایط جایز است"
- کلمات عامیانه را به اصطلاح فقهی تبدیل کن
- keywords_ar: معادل عربی اگر در متون فقهی رایج است

سوال اصلی: {original}
سوال نرمال‌شده: {normalized}

فقط JSON بده."""

    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=400,
            response_format={"type": "json_object"}
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        logger.warning(f"Analysis error: {e}")
        return {
            "keywords_fa": [],
            "keywords_ar": [],
            "section": "",
            "formal_query": normalized,
            "keyword_query": normalized,
            "expanded_query": normalized,
            "is_about_prohibition": False
        }


# ── جستجوی مستقیم شماره مسئله ───────────────────────────────
def search_by_number(num: int) -> List[Dict]:
    try:
        col = get_collection()
        res = col.get(where={"problem_number": num}, include=["documents", "metadatas"])
        chunks = []
        if res and res["documents"]:
            for doc, meta in zip(res["documents"], res["metadatas"]):
                chunks.append({
                    "text": doc,
                    "problem_number": meta.get("problem_number", -1),
                    "section": meta.get("section", ""),
                    "subsection": meta.get("subsection", ""),
                    "section_path": meta.get("section_path", ""),
                    "source": meta.get("source", ""),
                    "similarity": 1.0,
                    "match_type": "exact"
                })
        return chunks
    except Exception as e:
        logger.warning(f"Direct search error: {e}")
        return []


# ── جستجوی semantic با چند query ────────────────────────────
def search_semantic(queries: List[str], n: int = 12, section_filter: str = None) -> List[Dict]:
    try:
        col = get_collection()
        if col.count() == 0:
            return []

        found: Dict[str, Dict] = {}

        for query in queries:
            if not query or not query.strip():
                continue
            emb = get_embeddings([query])[0]

            query_params = {
                "query_embeddings": [emb],
                "n_results": min(n, col.count()),
                "include": ["documents", "metadatas", "distances"]
            }
            if section_filter:
                query_params["where"] = {"section": section_filter}

            res = col.query(**query_params)
            if not res["documents"][0]:
                continue

            for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
                sim = round(1 - dist, 3)
                key = f"{meta.get('source')}_{meta.get('chunk_index')}"
                if key not in found or found[key]["similarity"] < sim:
                    found[key] = {
                        "text": doc,
                        "problem_number": meta.get("problem_number", -1),
                        "section": meta.get("section", ""),
                        "subsection": meta.get("subsection", ""),
                        "section_path": meta.get("section_path", ""),
                        "source": meta.get("source", ""),
                        "similarity": sim,
                        "match_type": "semantic"
                    }

        return sorted(found.values(), key=lambda x: x["similarity"], reverse=True)
    except Exception as e:
        logger.warning(f"Semantic search error: {e}")
        return []


# ── Reranking هوشمند ─────────────────────────────────────────
def smart_rerank(question: str, chunks: List[Dict]) -> List[Dict]:
    """فقط rerank کن وقتی واقعاً نیاز است"""
    if len(chunks) <= 3:
        return chunks
    if len(chunks) >= 2 and chunks[0]["similarity"] - chunks[1]["similarity"] > 0.15:
        return chunks[:6]
    return rerank(question, chunks[:8])


def rerank(question: str, chunks: List[Dict]) -> List[Dict]:
    if len(chunks) <= 2:
        return chunks

    items = "\n".join([f"[{i+1}] {c['text'][:250]}" for i, c in enumerate(chunks[:10])])
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"سوال: {question}\n\nهر متن را از 0 تا 10 بر اساس ارتباط با سوال امتیاز بده.\nفقط اعداد با کاما. مثال: 8,3,10,2,5"
                },
                {"role": "user", "content": items}
            ],
            temperature=0,
            max_tokens=60
        )
        scores_raw = r.choices[0].message.content.strip()
        scores = [float(s.strip()) for s in scores_raw.split(',') if s.strip()]
        for i, c in enumerate(chunks):
            c["rerank_score"] = scores[i] if i < len(scores) else 5.0
        return sorted(chunks, key=lambda x: x.get("rerank_score", 5), reverse=True)
    except Exception as e:
        logger.warning(f"Rerank error: {e}")
        return chunks


# ── جستجوی کامل ─────────────────────────────────────────────
def full_search(original: str, normalized: str, analysis: Dict) -> List[Dict]:
    found: Dict[str, Dict] = {}

    # ۱. جستجوی مستقیم شماره مسئله
    prob_num = (
        extract_problem_number(original)
        or extract_problem_number(normalized)
    )
    if prob_num:
        logger.info(f"Exact lookup: masaleh {prob_num}")
        for c in search_by_number(prob_num):
            found[f"exact_{prob_num}"] = c

    # ۲. ساخت queries بهینه (حداکثر 4 تا)
    queries = list(dict.fromkeys(filter(None, [
        original,
        normalized if normalized != original else None,
        analysis.get("formal_query", ""),
        analysis.get("keyword_query", ""),
    ])))[:4]

    # ۳. جستجوی semantic با فیلتر بخش
    section = analysis.get("section", "")
    section_filter = section if section in SECTION_PROBLEM_MAP else None

    semantic = search_semantic(queries, n=12, section_filter=section_filter)

    if section_filter and len(semantic) < 3:
        semantic_all = search_semantic(queries, n=12)
        semantic.extend(semantic_all)

    for c in semantic:
        key = f"sem_{c['source']}_{c['problem_number']}_{c['text'][:15]}"
        if key not in found:
            found[key] = c

    if not found:
        return []

    chunks = list(found.values())

    # ۴. فیلتر
    filtered = [c for c in chunks if c["similarity"] >= SIMILARITY_THRESHOLD]
    if not filtered:
        filtered = sorted(chunks, key=lambda x: x["similarity"], reverse=True)[:5]

    # ۵. exact matches اول بیایند
    exact = [c for c in filtered if c.get("match_type") == "exact"]
    rest = [c for c in filtered if c.get("match_type") != "exact"]

    if exact:
        reranked_rest = smart_rerank(original, rest[:8])[:4]
        return exact + reranked_rest

    return smart_rerank(original, filtered[:12])[:8]


# ── System Prompt ────────────────────────────────────────────
SYSTEM_PROMPT = """تو دستیار تخصصی رساله فقهی آیت‌الله سید علی محمد دستغیب هستی.

## قوانین مطلق:
1. **فقط** از متن مسائل رساله استفاده کن - هرگز از دانش عمومی خود استفاده نکن
2. اگر جواب در مسائل بود → کامل توضیح بده و **شماره مسئله** را ذکر کن
3. اگر جواب نبود → بگو: «این مسئله در رساله موجود نیست.»
4. سوالات عامیانه فارسی را کاملاً درک کن و جواب فقهی رسمی بده
5. اگر چند مسئله مرتبط بود، همه را ذکر کن
6. جواب را با بخش‌بندی واضح بده:
   - **حکم:** ...
   - **توضیح:** ...
   - **مرجع:** مسئله [شماره] - [نام بخش]

## موضوع سوال: {topic}
## کلمات کلیدی: {keywords}

{conversation_context}

## مسائل رساله:
{context}"""


# ── پاسخ‌دهی Streaming ──────────────────────────────────────
async def answer_question_stream(
    question: str,
    cancel_event: asyncio.Event,
    session_id: str = None
) -> AsyncGenerator[Dict, None]:
    """پاسخ streaming - کلمه به کلمه با قابلیت cancel"""

    question = question.strip()

    # Small talk
    st = is_small_talk(question)
    if st:
        yield {"type": "answer", "content": st, "done": False}
        yield {"type": "done", "sources": [], "keywords": [], "found_in_docs": True}
        return

    # بررسی فایل
    stats = get_collection_stats()
    if stats.get("total_chunks", 0) == 0:
        yield {"type": "answer", "content": "هنوز فایلی بارگذاری نشده.", "done": False}
        yield {"type": "done", "sources": [], "keywords": [], "found_in_docs": False}
        return

    # تشخیص زبان
    lang = detect_language(question)
    search_question = question

    if lang != "fa":
        yield {"type": "status", "content": "در حال ترجمه سوال..."}
        search_question = translate_to_farsi(question, lang)

    # ── مسیر سریع: جستجوی مستقیم شماره مسئله ──
    prob_num = extract_problem_number(question) or extract_problem_number(search_question)
    if prob_num:
        yield {"type": "status", "content": f"جستجوی مسئله {prob_num}..."}
        chunks = search_by_number(prob_num)
        if chunks:
            context = "\n\n".join([
                f"━━ مسئله {c['problem_number']} | {c.get('section_path', '')} ━━\n{c['text']}"
                for c in chunks
            ])

            conv_context = ""
            if session_id:
                conv_context = memory.get_context(session_id)
            conv_section = f"\n## مکالمه قبلی:\n{conv_context}" if conv_context else ""

            system_prompt = SYSTEM_PROMPT.format(
                topic="", keywords="",
                conversation_context=conv_section,
                context=context
            )
            system_prompt += ANSWER_IN_LANGUAGE_ADDENDUM.get(lang, "")

            yield {"type": "status", "content": "در حال تولید پاسخ..."}
            if cancel_event.is_set():
                return

            full_answer = ""
            try:
                stream = await async_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question}
                    ],
                    temperature=0.05, max_tokens=1500, stream=True
                )
                async for chunk in stream:
                    if cancel_event.is_set():
                        await stream.close()
                        return
                    if chunk.choices and chunk.choices[0].delta.content:
                        t = chunk.choices[0].delta.content
                        full_answer += t
                        yield {"type": "answer", "content": t, "done": False}
                        await asyncio.sleep(0)

                sources = [{
                    "filename": c["source"], "page": c["problem_number"],
                    "similarity": c["similarity"],
                    "label": f"مسئله {c['problem_number']}",
                    "section": c.get("section_path", c.get("section", ""))
                } for c in chunks]

                if session_id and full_answer:
                    memory.add_exchange(session_id, question, full_answer[:300])

                yield {"type": "done", "sources": sources[:6], "keywords": [], "found_in_docs": True}
                return
            except Exception as e:
                logger.error(f"Fast path error: {e}")
                yield {"type": "error", "content": f"خطا: {str(e)}"}
                return

    # ── مسیر عادی ──
    normalized = normalize_colloquial(search_question)

    yield {"type": "status", "content": "در حال تحلیل سوال..."}

    # اجرای موازی: تحلیل + embedding اولیه
    loop = asyncio.get_event_loop()
    analysis_task = loop.run_in_executor(None, analyze_question, search_question, normalized)
    embed_task = loop.run_in_executor(None, get_embeddings, [search_question])
    analysis, _initial_embeddings = await asyncio.gather(analysis_task, embed_task)

    yield {"type": "status", "content": "در حال جستجو در رساله..."}
    if cancel_event.is_set():
        return

    chunks = full_search(search_question, normalized, analysis)
    if not chunks:
        chunks = search_semantic([search_question, normalized], n=5)
        chunks = [c for c in chunks if c["similarity"] >= 0.10]

    if not chunks:
        yield {"type": "answer", "content": "این مسئله در رساله موجود نیست.", "done": False}
        yield {"type": "done", "sources": [], "keywords": [], "found_in_docs": False}
        return

    context_parts = []
    for c in chunks:
        num = c["problem_number"]
        path = c.get("section_path", c.get("section", ""))
        sim = c["similarity"]
        header = f"مسئله {num} | {path}" if num > 0 else f"توضیح | {path}"
        context_parts.append(f"━━ {header} (امتیاز: {sim:.2f}) ━━\n{c['text']}")
    context = "\n\n".join(context_parts)

    kws_fa = analysis.get("keywords_fa", [])
    kws_ar = analysis.get("keywords_ar", [])
    all_kws = kws_fa + kws_ar

    conv_context = ""
    if session_id:
        conv_context = memory.get_context(session_id)
    conv_section = f"\n## مکالمه قبلی:\n{conv_context}" if conv_context else ""

    system_prompt = SYSTEM_PROMPT.format(
        topic=analysis.get("section", ""),
        keywords="، ".join(all_kws[:8]),
        conversation_context=conv_section,
        context=context
    )
    system_prompt += ANSWER_IN_LANGUAGE_ADDENDUM.get(lang, "")

    yield {"type": "status", "content": "در حال تولید پاسخ..."}
    if cancel_event.is_set():
        return

    full_answer = ""
    try:
        stream = await async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.05, max_tokens=1500, stream=True
        )

        async for chunk in stream:
            if cancel_event.is_set():
                await stream.close()
                return
            if chunk.choices and chunk.choices[0].delta.content:
                token_text = chunk.choices[0].delta.content
                full_answer += token_text
                yield {"type": "answer", "content": token_text, "done": False}
                await asyncio.sleep(0)

        sources = []
        seen = set()
        for c in chunks:
            num = c["problem_number"]
            key = f"{c['source']}_{num}"
            if key not in seen:
                seen.add(key)
                sources.append({
                    "filename": c["source"], "page": num,
                    "similarity": c["similarity"],
                    "label": f"مسئله {num}" if num > 0 else "توضیح",
                    "section": c.get("section_path", c.get("section", ""))
                })

        not_found = any(p in full_answer for p in ["موجود نیست", "یافت نشد"])

        if session_id and full_answer:
            memory.add_exchange(session_id, question, full_answer[:300])

        yield {
            "type": "done",
            "sources": sources[:6],
            "keywords": kws_fa[:5],
            "found_in_docs": not not_found
        }

    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield {"type": "error", "content": f"خطا: {str(e)}"}
