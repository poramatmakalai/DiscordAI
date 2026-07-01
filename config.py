import os
from dotenv import load_dotenv

load_dotenv()

# =====================================================
# Discord
# =====================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

BOT_NAME = os.getenv("BOT_NAME", "PhuAi")

# ALLOWED_CHANNELS อ่านจาก .env เป็น comma-separated string เช่น
#   ALLOWED_CHANNELS=1521011933870948463,1234567890123456789
# ถ้าไม่มีใน .env จะ fallback ไปใช้ค่า default ด้านล่าง
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
# Gemini
# =====================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# แนะนำ
# gemini-3.1-flash-lite  (เร็ว ถูก เหมาะกับแชทบอททั่วไป)
# gemini-3-flash-preview (สมดุลคุณภาพ/ความเร็ว มี free tier)
#
# หมายเหตุ: ก่อน deploy จริง ควรเช็คชื่อโมเดลนี้กับเอกสาร Gemini API
# ล่าสุดอีกครั้ง เพราะถ้าชื่อโมเดลไม่มีจริง/เปลี่ยนชื่อไปแล้ว จะได้ error
# 404 "model not found" ตอนเรียก API ไม่ใช่ error โควต้า

MODEL_NAME = "gemini-3.1-flash-lite"   # ตัวที่บอทใช้ตอบแชทหลัก (GA, ไม่ใช่ -preview ที่เลิกใช้แล้ว)

# =====================================================
# AI
# =====================================================

TEMPERATURE = 0.5
TOP_P = 0.9
TOP_K = 20

# ลดจาก 8192 -> 1024: คำตอบยาวเกิน 4096 token (~3,000 คำ) แทบไม่จำเป็น
# สำหรับแชทบอท Discord และ output token มีราคาแพงกว่า input token หลายเท่า
# ลดเพดานนี้ช่วยตัดต้นทุนได้จริงโดยแทบไม่กระทบการใช้งานปกติ
# ถ้าต้องการให้ตอบยาวกว่านี้ (เช่นเขียนโค้ดยาวๆ) ปรับค่านี้ขึ้นได้ตามต้องการ
MAX_OUTPUT_TOKENS = 768

# =====================================================
# Vision
# =====================================================

ENABLE_VISION = True

MAX_IMAGE_SIZE_MB = 15

# หมายเหตุ: ต้องตรงกับ _IMAGE_EXTS ใน ai/gemini.py เสมอ (รวม .bmp ด้วย)
# ก่อนหน้านี้ config ชุดนี้ไม่มี .bmp ทำให้ผู้ใช้แนบ .bmp มาแล้วโดนเขี่ยทิ้ง
# เป็น "ไม่รองรับ" ทั้งที่ backend (gemini.py) รองรับจริง
SUPPORTED_IMAGE_TYPES = {

    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",

}

# =====================================================
# File Reader
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
# Google Search
# =====================================================

ENABLE_GOOGLE_SEARCH = True

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
# Prompt
# =====================================================

# ai/gemini.py import SYSTEM_PROMPT ตรงจาก ai/system_prompt.py อยู่แล้ว
# (from ai.system_prompt import SYSTEM_PROMPT) ถ้าต้องการย้ายไฟล์ system
# prompt ไปที่อื่น ให้แก้ import ตรงนั้น ไม่ใช่ค่าคงที่ path ตรงนี้
# (เดิมมี SYSTEM_PROMPT_FILE ประกาศไว้แต่ไม่มีจุดไหนอ่านค่านี้ไปใช้จริง
# จึงตัดออกเพื่อไม่ให้เข้าใจผิดว่าแก้ path ตรงนี้แล้วจะมีผล)

# =====================================================
# Limits
# =====================================================

# ใช้ค่าเดียวกันทั้งโปรเจกต์ — ทั้ง main.py (ตัด preview ระหว่าง streaming)
# และ utils/formatter.py (ตัดข้อความสุดท้ายก่อนส่งจริง) import ค่านี้จาก
# config แทนที่จะประกาศ DISCORD_LIMIT ซ้ำอีกตัวแยกกัน (ของเดิมมี 2 ค่า
# ไม่ตรงกัน: config=1500, formatter.py=2000)
DISCORD_MESSAGE_LIMIT = 2000

MAX_ATTACHMENTS = 4

# =====================================================
# Debug
# =====================================================

DEBUG = False