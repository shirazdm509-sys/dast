"""
logging_config.py - تنظیمات لاگینگ ساختاریافته
- لاگ فایل با rotation
- لاگ خطاها به فایل جداگانه
"""

import os
import logging
import logging.handlers

LOG_DIR = os.environ.get("LOG_DIR", "./data/logs")
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logging():
    formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Error-only handler
    error_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "errors.log"),
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(error_handler)
    root.addHandler(console_handler)
