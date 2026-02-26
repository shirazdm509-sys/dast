"""
session_memory.py - مدیریت حافظه مکالمه برای سوالات پیگیری
- ذخیره آخرین N تبادل به ازای هر session
- TTL برای حذف خودکار session‌های قدیمی
"""

import threading
from datetime import datetime, timezone


class SessionMemory:
    def __init__(self, max_turns: int = 5, ttl_minutes: int = 30):
        self.max_turns = max_turns
        self.ttl_minutes = ttl_minutes
        self._store = {}  # session_id -> {messages: [...], last_active: datetime}
        self._lock = threading.Lock()

    def add_exchange(self, session_id: str, question: str, answer_summary: str):
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = {"messages": [], "last_active": None}
            entry = self._store[session_id]
            entry["messages"].append({
                "q": question[:200],
                "a": answer_summary[:300],
            })
            entry["messages"] = entry["messages"][-self.max_turns:]
            entry["last_active"] = datetime.now(timezone.utc)

    def get_context(self, session_id: str) -> str:
        with self._lock:
            entry = self._store.get(session_id)
            if not entry:
                return ""
            # بررسی TTL
            age = (datetime.now(timezone.utc) - entry["last_active"]).total_seconds()
            if age > self.ttl_minutes * 60:
                del self._store[session_id]
                return ""
            # فرمت به عنوان context مکالمه
            lines = []
            for ex in entry["messages"]:
                lines.append(f"سوال قبلی: {ex['q']}")
                lines.append(f"پاسخ قبلی: {ex['a']}")
            return "\n".join(lines)

    def clear_session(self, session_id: str):
        with self._lock:
            self._store.pop(session_id, None)

    def cleanup(self):
        """حذف session‌های منقضی - باید دوره‌ای فراخوانی شود"""
        now = datetime.now(timezone.utc)
        with self._lock:
            expired = [
                sid for sid, data in self._store.items()
                if (now - data["last_active"]).total_seconds() > self.ttl_minutes * 60
            ]
            for sid in expired:
                del self._store[sid]
        return len(expired)


# Singleton instance
memory = SessionMemory()
