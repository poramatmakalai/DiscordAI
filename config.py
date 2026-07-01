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

# Ollama unload โมเดลออกจาก RAM อัตโนมัติถ้าไม่มี request เข้ามาเกินเวลานี้
# (default ของ Ollama เองคือ 5 นาที) — พอ unload แล้ว request ถัดไปต้องเสีย
# เวลาโหลดโมเดลใหม่จากดิสก์อีกรอบ (มักช้ากว่าตอบจริงเสียอีกบนเครื่องไม่มี
# การ์ดจอแยก) ตั้งไว้นานขึ้นหน่อยเพื่อให้โมเดล "อุ่น" ค้างไว้ในแชทที่คุยถี่ๆ
# กัน re-load ซ้ำๆ โดยไม่จำเป็น ปรับได้ผ่าน .env (OLLAMA_KEEP_ALIVE)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "5m")

# ขนาด context window ที่ส่งให้ Ollama ต่อ request (จำนวน token)
# ระบุตรงๆ แทนที่จะปล่อยให้ใช้ default ของแต่ละโมเดล เพราะ:
#   - ถ้า context เล็กเกินไป prompt ยาวๆ (มีผลค้นเว็บ/ไฟล์แนบ) อาจถูกตัด
#     ท้าย system prompt หายไปเงียบๆ โดยไม่มี error ใดๆ
#   - ถ้าใหญ่เกินไปโดยไม่จำเป็น จะกิน RAM และช้าลงมากบน CPU ล้วน
# 4096 พอสำหรับ system prompt + เอกสารแนบ + ผลค้นเว็บในแชทบอทแบบ single-turn
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))

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

MAX_IMAGE_SIZE_MB = 10

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

MAX_FILE_SIZE_MB = 10

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

# "auto" (แนะนำ) = ค้นเว็บเฉพาะข้อความที่ดูจำเป็นต้องใช้ข้อมูลล่าสุด/ภายนอก
#                  (มีคำถาม, คำว่า "ล่าสุด/วันนี้/ราคา/ข่าว" ฯลฯ, หรือมี URL)
#                  ข้อความทั่วไป เช่น ทักทาย/คุยเล่น/ขอโค้ด จะไม่ยิง request
#                  ไป DuckDuckGo เลย → ตอบเร็วขึ้นชัดเจนเพราะตัด network
#                  round-trip + parse HTML ทิ้งไปในเคสที่ไม่จำเป็น
# "always"       = ค้นทุกข้อความที่มีตัวอักษร (พฤติกรรมเดิม ช้ากว่าแต่ชัวร์กว่า)
SEARCH_MODE = os.getenv("SEARCH_MODE", "auto")

# =====================================================
# Streaming
# =====================================================

ENABLE_STREAMING = False

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