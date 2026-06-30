import logging
from pathlib import Path

import config

# สร้างโฟลเดอร์ logs ถ้ายังไม่มี
Path("logs").mkdir(exist_ok=True)

# อ่าน LOG_LEVEL จาก config (เช่น "DEBUG", "INFO", "WARNING", "ERROR")
_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

logger = logging.getLogger("DiscordAI")
logger.setLevel(_level)

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s"
)

# ป้องกันการเพิ่ม Handler ซ้ำ
if not logger.handlers:

    file_handler = logging.FileHandler(
        "logs/bot.log",
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)