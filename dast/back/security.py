"""
security.py - ماژول امنیتی پیشرفته
- Rate limiting با SQLite (مقاوم به ریستارت)
- Input sanitization
- XSS/SQL injection prevention
- Brute force protection
- bcrypt password hashing
"""

import os
import re
import time
import hashlib
import hmac
import sqlite3
import threading
import logging
from typing import Optional
from fastapi import HTTPException, Request

try:
    import bcrypt
except ImportError:
    bcrypt = None

logger = logging.getLogger("resaleh.security")

# ── Rate Limiting with SQLite ─────────────────────────────────
DATA_DIR = os.environ.get("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)
RATE_DB = os.path.join(DATA_DIR, "rate_limits.db")
_db_lock = threading.Lock()

RATE_LIMITS = {
    "general":   (60, 60),    # 60 req / 60s
    "ask":       (20, 60),    # 20 ask / 60s
    "login":     (5,  300),   # 5 tries / 5min
}


def _get_db():
    conn = sqlite3.connect(RATE_DB, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            ip TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            ip TEXT PRIMARY KEY,
            unblock_time REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_failures (
            ip TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_req_ip ON requests(ip, endpoint)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_ip ON login_failures(ip)")
    conn.commit()
    return conn


# Initialize DB on import
try:
    _get_db().close()
except Exception as e:
    logger.warning(f"Rate limit DB init warning: {e}")


def check_rate(ip: str, endpoint: str = "general"):
    now = time.time()
    with _db_lock:
        db = _get_db()
        try:
            # بررسی block
            row = db.execute("SELECT unblock_time FROM blocks WHERE ip=?", (ip,)).fetchone()
            if row:
                if now < row[0]:
                    wait = int(row[0] - now)
                    raise HTTPException(429, f"IP مسدود شده. {wait} ثانیه صبر کنید.")
                else:
                    db.execute("DELETE FROM blocks WHERE ip=?", (ip,))

            limit, window = RATE_LIMITS.get(endpoint, RATE_LIMITS["general"])

            # حذف رکوردهای قدیمی
            db.execute("DELETE FROM requests WHERE timestamp < ?", (now - window,))

            # شمارش درخواست‌های اخیر
            count = db.execute(
                "SELECT COUNT(*) FROM requests WHERE ip=? AND endpoint=?",
                (ip, endpoint)
            ).fetchone()[0]

            if count >= limit:
                if count >= limit * 2:
                    db.execute(
                        "INSERT OR REPLACE INTO blocks VALUES (?, ?)",
                        (ip, now + 600)
                    )
                db.commit()
                raise HTTPException(429, "درخواست‌ها بیش از حد مجاز. کمی صبر کنید.")

            db.execute(
                "INSERT INTO requests VALUES (?, ?, ?)",
                (ip, endpoint, now)
            )
            db.commit()
        finally:
            db.close()


def check_login(ip: str, success: bool = False):
    now = time.time()
    with _db_lock:
        db = _get_db()
        try:
            if success:
                db.execute("DELETE FROM login_failures WHERE ip=?", (ip,))
                db.commit()
                return

            # حذف رکوردهای قدیمی‌تر از 5 دقیقه
            db.execute("DELETE FROM login_failures WHERE timestamp < ?", (now - 300,))

            count = db.execute(
                "SELECT COUNT(*) FROM login_failures WHERE ip=?", (ip,)
            ).fetchone()[0]

            if count >= 5:
                db.execute(
                    "INSERT OR REPLACE INTO blocks VALUES (?, ?)",
                    (ip, now + 900)
                )
                db.commit()
                raise HTTPException(429, "حساب موقتاً مسدود شد. ۱۵ دقیقه صبر کنید.")

            db.execute("INSERT INTO login_failures VALUES (?, ?)", (ip, now))
            db.commit()
        finally:
            db.close()


def cleanup_rate_db():
    """پاکسازی دوره‌ای - باید هر ساعت فراخوانی شود"""
    now = time.time()
    with _db_lock:
        db = _get_db()
        try:
            db.execute("DELETE FROM requests WHERE timestamp < ?", (now - 3600,))
            db.execute("DELETE FROM login_failures WHERE timestamp < ?", (now - 3600,))
            db.execute("DELETE FROM blocks WHERE unblock_time < ?", (now,))
            db.commit()
        finally:
            db.close()


# ── Input Sanitization ────────────────────────────────────────
DANGEROUS_PATTERNS = [
    r'<script[^>]*>.*?</script>',
    r'javascript\s*:',
    r'on\w+\s*=',
    r'<iframe',
    r'document\.cookie',
    r'eval\s*\(',
    r'window\.location',
    r'\.\./\.\.',           # path traversal
    r'%2e%2e',              # encoded path traversal
    r'union\s+select',      # SQL injection
    r'drop\s+table',
    r'insert\s+into',
    r';\s*--',
    r'<img[^>]+onerror',    # img XSS
    r'<svg[^>]+onload',     # svg XSS
    r'expression\s*\(',     # CSS expression
    r'url\s*\(\s*data:',    # data URI in CSS
]


def sanitize_input(text: str, max_len: int = 1000) -> str:
    if not text:
        return ""

    # محدودیت طول
    text = text[:max_len]

    # حذف null bytes و control characters
    text = text.replace('\x00', '')
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # بررسی patterns خطرناک
    text_lower = text.lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL):
            raise HTTPException(400, "ورودی نامعتبر است")

    return text.strip()


def sanitize_username(username: str) -> str:
    username = username.strip()[:50]
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', username):
        raise HTTPException(400, "نام کاربری فقط می‌تواند شامل حروف لاتین، اعداد و _-. باشد")
    if len(username) < 3:
        raise HTTPException(400, "نام کاربری باید حداقل ۳ کاراکتر باشد")
    return username


def sanitize_password(password: str) -> str:
    if len(password) < 6:
        raise HTTPException(400, "رمز عبور باید حداقل ۶ کاراکتر باشد")
    if len(password) > 128:
        raise HTTPException(400, "رمز عبور خیلی طولانی است")
    return password


# ── Password Hashing with bcrypt ──────────────────────────────
def hash_password(password: str) -> str:
    """هش رمز عبور با bcrypt (یا SHA-256 به عنوان fallback)"""
    if bcrypt:
        return bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')
    # Fallback اگر bcrypt نصب نبود
    logger.warning("bcrypt not available, using SHA-256 fallback")
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    """
    بررسی رمز عبور.
    از bcrypt استفاده می‌کند و fallback برای هش‌های قدیمی SHA-256 دارد.
    Returns: (is_valid, needs_rehash)
    """
    # اول bcrypt امتحان کن
    if bcrypt and hashed.startswith('$2'):
        try:
            return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            return False

    # Fallback برای هش‌های قدیمی SHA-256
    old_hash = hashlib.sha256(plain.encode('utf-8')).hexdigest()
    if hmac.compare_digest(old_hash, hashed):
        return True

    return False


def needs_rehash(hashed: str) -> bool:
    """آیا هش باید با bcrypt دوباره ساخته شود؟"""
    if bcrypt and not hashed.startswith('$2'):
        return True
    return False


# ── Security Headers ──────────────────────────────────────────
SECURITY_HEADERS = {
    "X-Content-Type-Options":    "nosniff",
    "X-Frame-Options":           "DENY",
    "X-XSS-Protection":          "1; mode=block",
    "Referrer-Policy":           "strict-origin-when-cross-origin",
    "Permissions-Policy":        "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy":   (
        "default-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' https://ai.dastgheibqoba.info; "
        "font-src 'self' https://fonts.gstatic.com; "
        "frame-ancestors 'none'"
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        # اعتبارسنجی ساده IP
        if re.match(r'^[\d\.a-fA-F:]+$', ip):
            return ip
    return request.client.host if request.client else "0.0.0.0"
