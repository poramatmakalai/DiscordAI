import asyncio
import sqlite3
from pathlib import Path

# สร้างโฟลเดอร์ database ถ้ายังไม่มี
Path("database").mkdir(exist_ok=True)

DATABASE = "database/database.db"


def connect():
    conn = sqlite3.connect(
        DATABASE,
        check_same_thread=False,
    )

    # WAL mode: อนุญาตให้อ่านพร้อมกับเขียนได้โดยไม่ติด "database is locked"
    # ง่ายและทนกว่า DELETE mode (default) มากเวลามี background task
    # (เช่น ai/extractor.py) เขียน DB พร้อมกับ flow หลักใน main.py
    conn.execute("PRAGMA journal_mode=WAL;")

    # busy_timeout: ถ้าเจอ lock จริงๆ (เช่น checkpoint กำลังทำงาน)
    # ให้ sqlite รอแล้ว retry เองภายใน driver แทนที่จะ throw ทันที
    conn.execute("PRAGMA busy_timeout=5000;")

    return conn


db = connect()

# หมายเหตุ: ห้ามใช้ cursor ตัวนี้ร่วมกันข้าม coroutine/background task
# (เช่น extract_and_save ที่รันผ่าน asyncio.create_task พร้อมกับ flow หลัก)
# เพราะ sqlite3 cursor ตัวเดียวกันถ้าถูกเรียกแทรกกันจะทำให้ query ผลลัพธ์ผิดเพี้ยนได้
# ให้ใช้ db.cursor() สร้างใหม่ทุกครั้งที่ query แทน (ดู memory/manager.py, memory/long_memory.py)
cursor = db.cursor()

# ── Write lock ──────────────────────────────────────────────────────────────
# WAL mode ช่วยให้ "อ่าน" พร้อมกับ "เขียน" ได้ แต่การ "เขียน" พร้อมกัน
# จากหลาย coroutine ยังควรเรียงคิวกันอยู่ดี (SQLite อนุญาตแค่ 1 writer
# ในเวลาเดียวกัน) ใช้ asyncio.Lock() นี้ครอบทุกจุดที่ทำ INSERT/UPDATE/DELETE
# จาก coroutine (memory/manager.py, memory/long_memory.py) เพื่อกัน race
# ระหว่าง flow หลักกับ background task ของ ai/extractor.py แบบชัวร์ๆ
write_lock = asyncio.Lock()


def initialize():

    # =========================
    # Chat History
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memory (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        guild_id INTEGER NOT NULL,

        channel_id INTEGER NOT NULL,

        user_id INTEGER NOT NULL,

        role TEXT NOT NULL,

        content TEXT NOT NULL,

        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    )
    """)

    # =========================
    # Long Memory
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS long_memory (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        guild_id INTEGER NOT NULL,

        user_id INTEGER NOT NULL,

        memory_key TEXT NOT NULL,

        memory_value TEXT NOT NULL,

        updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(guild_id,user_id,memory_key)

    )
    """)

    db.commit()


initialize()