"""
main.py - رساله دستغیب v4
امکانات:
- JWT + Rate Limiting مقاوم به ریستارت
- پشتیبانی دوطرفه (کاربر ↔ ادمین)
- گزارش اشکال
- پنل ادمین کامل با آنالیتیکس
- لاگینگ ساختاریافته
- عملیات اتمیک فایل JSON
- bcrypt password hashing
- حافظه مکالمه
- لاگ سوالات برای آنالیتیکس
"""

import os
import json
import uuid
import fcntl
import asyncio
import tempfile
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import jwt
from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from logging_config import setup_logging
setup_logging()

logger = logging.getLogger("resaleh")

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required")
ALGORITHM = "HS256"
TOKEN_HOURS = 24

DATA_DIR = os.environ.get("DATA_DIR", "./data")
LOG_DIR = os.environ.get("LOG_DIR", "./data/logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

USERS_FILE = f"{DATA_DIR}/users.json"
BUGS_FILE = f"{DATA_DIR}/bugs.json"
SUPPORT_FILE = f"{DATA_DIR}/support.json"
SETTINGS_FILE = f"{DATA_DIR}/settings.json"
QUESTIONS_LOG_FILE = f"{DATA_DIR}/questions_log.json"
BROADCAST_FILE = f"{DATA_DIR}/broadcasts.json"

from security import (
    check_rate, check_login, sanitize_input, sanitize_username,
    sanitize_password, hash_password, verify_password, needs_rehash,
    SECURITY_HEADERS, get_client_ip, cleanup_rate_db
)


# ── data helpers (atomic file operations) ─────────────────────
def rj(path, default):
    if not os.path.exists(path):
        wj(path, default)
        return default
    try:
        with open(path, encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Error reading {path}: {e}")
        return default


def wj(path, data):
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_users():
    default_admin_pw = os.environ.get("ADMIN_DEFAULT_PASSWORD", "CHANGE-ME-NOW")
    default = {"admin": {
        "password": hash_password(default_admin_pw),
        "role": "admin",
        "created_at": datetime.now(timezone.utc).isoformat()
    }}
    return rj(USERS_FILE, default)


def get_settings():
    return rj(SETTINGS_FILE, {
        "site_title":    "رساله آیت‌الله سید علی محمد دستغیب",
        "site_subtitle": "دستیار هوشمند احکام فقهی",
        "primary_color": "#7c6af7",
        "gold_color":    "#e8c97a",
        "welcome_text":  "سوال فقهی خود را بپرسید. جواب با ذکر شماره مسئله ارائه می‌شود.",
        "max_q_len":     500,
    })


# ── JWT ──────────────────────────────────────────────────────
def make_token(username: str, role: str) -> str:
    return jwt.encode(
        {"sub": username, "role": role,
         "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)},
        SECRET_KEY, algorithm=ALGORITHM)


def check_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "توکن منقضی شده. دوباره وارد شوید.")
    except jwt.PyJWTError:
        raise HTTPException(401, "توکن نامعتبر")


bearer = HTTPBearer(auto_error=False)


async def cur_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    if not creds:
        raise HTTPException(401, "لطفاً وارد شوید")
    return check_token(creds.credentials)


async def admin_only(u=Depends(cur_user)):
    if u.get("role") != "admin":
        raise HTTPException(403, "فقط ادمین دسترسی دارد")
    return u


# ── FastAPI ──────────────────────────────────────────────────
ENABLE_DOCS = os.environ.get("ENABLE_DOCS", "false").lower() == "true"
app = FastAPI(
    title="رساله دستغیب",
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

app.add_middleware(CORSMiddleware,
    allow_origins=[
        "https://ai.dastgheibqoba.info",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_mid(request: Request, call_next):
    ip = get_client_ip(request)
    if not request.url.path.startswith("/auth"):
        endpoint = "ask" if "/ask" in request.url.path else "general"
        try:
            check_rate(ip, endpoint)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    resp = await call_next(request)
    resp.headers.update(SECURITY_HEADERS)
    return resp


# ── Periodic cleanup ─────────────────────────────────────────
@app.on_event("startup")
async def startup_cleanup():
    from session_memory import memory

    async def periodic_cleanup():
        while True:
            await asyncio.sleep(3600)
            try:
                cleanup_rate_db()
                memory.cleanup()
            except Exception as e:
                logger.warning(f"Periodic cleanup error: {e}")

    asyncio.create_task(periodic_cleanup())
    logger.info("Resaleh API v4 started")


# ── Models ────────────────────────────────────────────────────
class LoginReq(BaseModel):
    username: str
    password: str

class AskReq(BaseModel):
    question: str
    session_id: Optional[str] = None

class BugReq(BaseModel):
    title: str
    description: str
    question: Optional[str] = None

class SupportReq(BaseModel):
    subject: str
    message: str

class ReplyReq(BaseModel):
    message: str

class UserReq(BaseModel):
    username: str
    password: str
    role: str = "user"

class PwReq(BaseModel):
    new_password: str

class SettingsReq(BaseModel):
    settings: dict

class BroadcastReq(BaseModel):
    message: str
    title: str = ""


# ── active streams ────────────────────────────────────────────
streams: dict = {}


# ── Question logging for analytics ───────────────────────────
def log_question(username: str, question: str):
    try:
        log = rj(QUESTIONS_LOG_FILE, [])
        log.append({
            "username": username,
            "question": question[:200],
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        if len(log) > 10000:
            log = log[-10000:]
        wj(QUESTIONS_LOG_FILE, log)
    except Exception as e:
        logger.warning(f"Question logging error: {e}")


# ── ROUTES ───────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "ok", "service": "رساله دستغیب", "version": "4.0"}


@app.get("/settings/public")
async def pub_settings():
    s = get_settings()
    return {k: v for k, v in s.items() if k != "max_q_len"}


# ── AUTH ─────────────────────────────────────────────────────
@app.post("/auth/login")
async def login(req: LoginReq, request: Request):
    ip = get_client_ip(request)
    check_rate(ip, "login")
    try:
        un = sanitize_username(req.username)
        pw = sanitize_password(req.password)
    except HTTPException as e:
        raise e
    users = get_users()
    u = users.get(un)
    if not u or not verify_password(pw, u["password"]):
        check_login(ip, success=False)
        raise HTTPException(401, "نام کاربری یا رمز اشتباه است")
    check_login(ip, success=True)

    # مهاجرت خودکار از SHA-256 به bcrypt
    if needs_rehash(u["password"]):
        users[un]["password"] = hash_password(pw)
        wj(USERS_FILE, users)
        logger.info(f"Password rehashed for user: {un}")

    return {
        "access_token": make_token(un, u["role"]),
        "username": un,
        "role": u["role"]
    }


@app.get("/auth/me")
async def me(u=Depends(cur_user)):
    return {"username": u["sub"], "role": u["role"]}


# ── ASK streaming ─────────────────────────────────────────────
@app.post("/ask")
async def ask(req: AskReq, u=Depends(cur_user)):
    from retriever import answer_question_stream
    from ingestion import get_collection_stats

    stats = get_collection_stats()
    if stats.get("total_chunks", 0) == 0:
        return JSONResponse({
            "answer": "هنوز فایلی بارگذاری نشده.",
            "sources": [], "found_in_docs": False, "keywords": []
        })

    sid = req.session_id or str(uuid.uuid4())
    ev = asyncio.Event()
    streams[sid] = ev

    log_question(u["sub"], req.question)

    async def gen():
        try:
            async for chunk in answer_question_stream(req.question, ev, session_id=sid):
                if ev.is_set():
                    yield f"data: {json.dumps({'type':'cancelled'})}\n\n"
                    break
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
        finally:
            streams.pop(sid, None)

    return StreamingResponse(gen(),
        media_type="text/event-stream",
        headers={
            "X-Session-ID": sid,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        })


@app.post("/ask/cancel/{sid}")
async def cancel(sid: str, u=Depends(cur_user)):
    if sid in streams:
        streams[sid].set()
        return {"cancelled": True}
    return {"cancelled": False}


# ── FILES ────────────────────────────────────────────────────
@app.get("/files")
async def files(u=Depends(cur_user)):
    from ingestion import get_ingested_files
    return {"files": get_ingested_files()}


@app.get("/stats")
async def stats(u=Depends(cur_user)):
    from ingestion import get_collection_stats
    return get_collection_stats()


# ── BUGS ─────────────────────────────────────────────────────
@app.post("/bugs")
async def submit_bug(req: BugReq, u=Depends(cur_user)):
    bugs = rj(BUGS_FILE, [])
    bug = {
        "id": str(uuid.uuid4())[:8],
        "username": u["sub"],
        "title": sanitize_input(req.title, 200),
        "description": sanitize_input(req.description, 1000),
        "question": sanitize_input(req.question or "", 500),
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    bugs.insert(0, bug)
    wj(BUGS_FILE, bugs)
    return {"success": True, "id": bug["id"]}


@app.get("/bugs")
async def get_bugs(u=Depends(admin_only)):
    bugs = rj(BUGS_FILE, [])
    return {
        "bugs": bugs,
        "total": len(bugs),
        "open": sum(1 for b in bugs if b["status"] == "open")
    }


@app.patch("/bugs/{bid}")
async def update_bug(bid: str, status: str, u=Depends(admin_only)):
    bugs = rj(BUGS_FILE, [])
    for b in bugs:
        if b["id"] == bid:
            b["status"] = status
            b["updated_at"] = datetime.now(timezone.utc).isoformat()
            break
    wj(BUGS_FILE, bugs)
    return {"success": True}


# ── SUPPORT ───────────────────────────────────────────────────
@app.post("/support")
async def new_ticket(req: SupportReq, u=Depends(cur_user)):
    tickets = rj(SUPPORT_FILE, [])
    ticket = {
        "id": str(uuid.uuid4())[:8],
        "username": u["sub"],
        "subject": sanitize_input(req.subject, 200),
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "messages": [{
            "from": u["sub"], "role": "user",
            "text": sanitize_input(req.message, 2000),
            "at": datetime.now(timezone.utc).isoformat()
        }]
    }
    tickets.insert(0, ticket)
    wj(SUPPORT_FILE, tickets)
    return {"success": True, "id": ticket["id"]}


@app.get("/support")
async def list_tickets(u=Depends(cur_user)):
    tickets = rj(SUPPORT_FILE, [])
    if u["role"] == "admin":
        return {"tickets": tickets}
    return {"tickets": [t for t in tickets if t["username"] == u["sub"]]}


@app.get("/support/{tid}")
async def get_ticket(tid: str, u=Depends(cur_user)):
    for t in rj(SUPPORT_FILE, []):
        if t["id"] == tid:
            if u["role"] != "admin" and t["username"] != u["sub"]:
                raise HTTPException(403, "دسترسی ندارید")
            return t
    raise HTTPException(404, "تیکت یافت نشد")


@app.post("/support/{tid}/reply")
async def reply(tid: str, req: ReplyReq, u=Depends(cur_user)):
    tickets = rj(SUPPORT_FILE, [])
    for t in tickets:
        if t["id"] == tid:
            if u["role"] != "admin" and t["username"] != u["sub"]:
                raise HTTPException(403, "دسترسی ندارید")
            t["messages"].append({
                "from": u["sub"], "role": u["role"],
                "text": sanitize_input(req.message, 2000),
                "at": datetime.now(timezone.utc).isoformat()
            })
            t["status"] = "answered" if u["role"] == "admin" else "open"
            wj(SUPPORT_FILE, tickets)
            return {"success": True}
    raise HTTPException(404)


@app.patch("/support/{tid}/close")
async def close_ticket(tid: str, u=Depends(admin_only)):
    tickets = rj(SUPPORT_FILE, [])
    for t in tickets:
        if t["id"] == tid:
            t["status"] = "closed"
            wj(SUPPORT_FILE, tickets)
            return {"success": True}
    raise HTTPException(404)


# ── ADMIN USERS ───────────────────────────────────────────────
@app.get("/admin/users")
async def list_users(u=Depends(admin_only)):
    users = get_users()
    return {"users": [
        {"username": k, "role": v["role"], "created_at": v.get("created_at", "")}
        for k, v in users.items()
    ]}


@app.post("/admin/users")
async def create_user(req: UserReq, u=Depends(admin_only)):
    un = sanitize_username(req.username)
    pw = sanitize_password(req.password)
    users = get_users()
    if un in users:
        raise HTTPException(400, "این کاربر از قبل وجود دارد")
    if req.role not in ("admin", "user"):
        raise HTTPException(400, "نقش نامعتبر")
    users[un] = {
        "password": hash_password(pw),
        "role": req.role,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    wj(USERS_FILE, users)
    return {"success": True}


@app.delete("/admin/users/{uname}")
async def del_user(uname: str, u=Depends(admin_only)):
    if uname == "admin":
        raise HTTPException(400, "نمی‌توان ادمین اصلی را حذف کرد")
    users = get_users()
    if uname not in users:
        raise HTTPException(404, "کاربر یافت نشد")
    del users[uname]
    wj(USERS_FILE, users)
    return {"success": True}


@app.patch("/admin/users/{uname}/password")
async def change_pw(uname: str, req: PwReq, u=Depends(admin_only)):
    pw = sanitize_password(req.new_password)
    users = get_users()
    if uname not in users:
        raise HTTPException(404, "کاربر یافت نشد")
    users[uname]["password"] = hash_password(pw)
    wj(USERS_FILE, users)
    return {"success": True}


# ── ADMIN SETTINGS ────────────────────────────────────────────
@app.get("/admin/settings")
async def admin_settings(u=Depends(admin_only)):
    return get_settings()


@app.put("/admin/settings")
async def save_settings(req: SettingsReq, u=Depends(admin_only)):
    current = get_settings()
    allowed = {
        "site_title", "site_subtitle", "primary_color", "gold_color",
        "welcome_text", "max_q_len",
        "logo_url", "bg_color", "surface_color", "text_color",
        "accent_color_2", "border_color", "header_bg",
        "font_family", "default_greeting", "footer_text",
        "maintenance_mode", "maintenance_message",
    }
    for k, v in req.settings.items():
        if k in allowed:
            current[k] = v
    wj(SETTINGS_FILE, current)
    return {"success": True}


# ── ADMIN ANALYTICS ──────────────────────────────────────────
@app.get("/admin/analytics")
async def analytics(u=Depends(admin_only)):
    users = get_users()
    bugs = rj(BUGS_FILE, [])
    tickets = rj(SUPPORT_FILE, [])
    questions = rj(QUESTIONS_LOG_FILE, [])

    today = datetime.now(timezone.utc).date().isoformat()
    questions_today = sum(
        1 for q in questions
        if q.get("timestamp", "").startswith(today)
    )

    from collections import Counter
    daily_counts = Counter()
    for q in questions:
        ts = q.get("timestamp", "")[:10]
        if ts:
            daily_counts[ts] += 1

    word_counts = Counter()
    for q in questions[-500:]:
        words = q.get("question", "").split()
        for w in words:
            if len(w) > 2:
                word_counts[w] += 1

    return {
        "total_users": len(users),
        "total_bugs": len(bugs),
        "open_bugs": sum(1 for b in bugs if b["status"] == "open"),
        "total_tickets": len(tickets),
        "open_tickets": sum(1 for t in tickets if t["status"] == "open"),
        "questions_today": questions_today,
        "questions_total": len(questions),
        "daily_questions": dict(sorted(daily_counts.items())[-7:]),
        "top_keywords": dict(word_counts.most_common(10)),
    }


# ── ADMIN LOGS ───────────────────────────────────────────────
@app.get("/admin/logs")
async def get_logs(u=Depends(admin_only), lines: int = 100, level: str = "all"):
    log_file = os.path.join(LOG_DIR, "errors.log" if level == "error" else "app.log")
    if not os.path.exists(log_file):
        return {"logs": []}
    try:
        with open(log_file, encoding="utf-8") as f:
            all_lines = f.readlines()
        return {"logs": all_lines[-lines:]}
    except Exception as e:
        return {"logs": [], "error": str(e)}


# ── ADMIN LOGO UPLOAD ────────────────────────────────────────
@app.post("/admin/logo")
async def upload_logo(file: UploadFile = File(...), u=Depends(admin_only)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "فقط فایل تصویری مجاز است")
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(400, "حجم فایل نباید بیشتر از 2 مگابایت باشد")
    logo_path = os.path.join(DATA_DIR, "logo.png")
    with open(logo_path, "wb") as f:
        f.write(content)
    settings = get_settings()
    settings["logo_url"] = "/data/logo.png"
    wj(SETTINGS_FILE, settings)
    return {"success": True, "url": "/data/logo.png"}


# ── BROADCAST ────────────────────────────────────────────────
@app.post("/admin/broadcast")
async def send_broadcast(req: BroadcastReq, u=Depends(admin_only)):
    broadcasts = rj(BROADCAST_FILE, [])
    broadcast = {
        "id": str(uuid.uuid4())[:8],
        "title": sanitize_input(req.title, 200),
        "message": sanitize_input(req.message, 1000),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "by": u["sub"]
    }
    broadcasts.insert(0, broadcast)
    if len(broadcasts) > 50:
        broadcasts = broadcasts[:50]
    wj(BROADCAST_FILE, broadcasts)
    return {"success": True, "id": broadcast["id"]}


@app.get("/broadcast/latest")
async def latest_broadcast(u=Depends(cur_user)):
    broadcasts = rj(BROADCAST_FILE, [])
    if broadcasts:
        return broadcasts[0]
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
