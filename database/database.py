import sqlite3
from pathlib import Path

# สร้างโฟลเดอร์ database ถ้ายังไม่มี
Path("database").mkdir(exist_ok=True)

DATABASE = "database/database.db"


def connect():
    return sqlite3.connect(
        DATABASE,
        check_same_thread=False
    )


db = connect()

# หมายเหตุ: ห้ามใช้ cursor ตัวนี้ร่วมกันข้าม coroutine/background task
# (เช่น extract_and_save ที่รันผ่าน asyncio.create_task พร้อมกับ flow หลัก)
# เพราะ sqlite3 cursor ตัวเดียวกันถ้าถูกเรียกแทรกกันจะทำให้ query ผลลัพธ์ผิดเพี้ยนได้
# ให้ใช้ db.cursor() สร้างใหม่ทุกครั้งที่ query แทน (ดู memory/manager.py, memory/long_memory.py)
cursor = db.cursor()


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