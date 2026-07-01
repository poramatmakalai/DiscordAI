import os
from dotenv import load_dotenv

load_dotenv()

# =====================================================
# Discord
# =====================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

BOT_NAME = os.getenv("BOT_NAME", "PhuAi")

_DEFAULT_ALLOWED_CHANNELS = [

    # ใส่ Channel ID ที่ต้องการให้ AI ตอบ (ใช้เฉพาะตอนไม่มี ALLOWED_CHANNELS ใน .env)
    1521011933870948463,

]

_raw_allowed_channels = os.getenv("ALLOWED_CHANNELS")

if _raw_allowed_channels:
    ALLOWED_CHANNELS = [
        int(cid.strip())
        for cid in _raw_allowed_channels.split(",")
        if cid.strip()
    ]
else:
    ALLOWED_CHANNELS = _DEFAULT_ALLOWED_CHANNELS

# =====================================================
# Local AI (Ollama) — ไม่มี API key ใดๆ ทั้งสิ้น
# =====================================================
#
# ต้องติดตั้ง Ollama เอง (https://ollama.com/download) แล้วรัน `ollama serve`
# บนเครื่องที่รันบอทนี้ ก่อนสั่งบอทให้ทำงาน
#
#   ollama pull llama3.2:3b     # โมเดลข้อความล้วน (เบา เหมาะกับ CPU ไม่มีการ์ดจอ)
#   ollama pull llava-phi3      # โมเดล vision (ดูรูปได้) — ตัวเล็กสุดที่ยังพอใช้ได้
#
# ถ้าเครื่องแรงพอ/มีเวลารอ อยากได้คุณภาพสูงขึ้น เปลี่ยนเป็น llama3.1:8b /
# qwen2.5-vl:7b ได้ แต่จะช้าลงมากถ้าไม่มีการ์ดจอแยก (เครื่องนี้ใช้ iGPU
# ในตัว Ryzen 5 7520U รันบน CPU เป็นหลัก)

OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
TEXT_MODEL   = os.getenv("TEXT_MODEL", "llama3.2:3b")
VISION_MODEL = os.getenv("VISION_MODEL", "llava-phi3")

# =====================================================
# AI (sampling params — ส่งเข้า Ollama options)
# =====================================================

TEMPERATURE = 0.5
TOP_P = 0.9
TOP_K = 20

# ลดจาก 8192 -> 1024: คำตอบยาวเกิน 4096 token (~3,000 คำ) แทบไม่จำเป็น
# สำหรับแชทบอท Discord — โมเดล local ยิ่งตอบยาวยิ่งช้ามากบน CPU
MAX_OUTPUT_TOKENS = 768

# =====================================================
# Vision
# =====================================================

ENABLE_VISION = True

MAX_IMAGE_SIZE_MB = 15

SUPPORTED_IMAGE_TYPES = {

    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",

}

# =====================================================
# File Reader — อ่าน/extract ข้อความจากไฟล์แบบ local ทั้งหมด (ai/document_reader.py)
# ไม่มีการอัปโหลดไฟล์ไปที่ไหนเลย
# =====================================================

ENABLE_FILE_READER = True

MAX_FILE_SIZE_MB = 15

SUPPORTED_DOCUMENTS = {

    ".pdf",
    ".docx",
    ".txt",
    ".csv",
    ".json"

}

# =====================================================
# Web Search — scrape DuckDuckGo (html.duckduckgo.com) ไม่ใช้ API key
# ⚠️ ฟีเจอร์นี้เป็นจุดเดียวที่ยังต่อเน็ตออกไปหาที่อื่น (นอกจาก Discord เอง)
#    ปิดได้ตรงนี้ถ้าต้องการให้บอทไม่ต่อเน็ตออกไปไหนเลยจริงๆ
# =====================================================

ENABLE_WEB_SEARCH = True

SEARCH_MAX_RESULTS = 3

# =====================================================
# Streaming
# =====================================================

ENABLE_STREAMING = True

STREAM_EDIT_INTERVAL = 1.0

# =====================================================
# Logging
# =====================================================

ENABLE_LOGGING = True

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# =====================================================
# Limits
# =====================================================

DISCORD_MESSAGE_LIMIT = 2000

MAX_ATTACHMENTS = 4

# =====================================================
# Debug
# =====================================================

DEBUG = False