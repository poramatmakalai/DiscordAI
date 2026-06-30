import config
from database.database import db, write_lock


class LongMemory:

    async def set(self, guild_id, user_id, key, value):

        async with write_lock:

            cur = db.cursor()

            cur.execute(
                """
                INSERT INTO long_memory(
                    guild_id, user_id, memory_key, memory_value
                )
                VALUES(?,?,?,?)
                ON CONFLICT(guild_id,user_id,memory_key)
                DO UPDATE SET
                memory_value=excluded.memory_value,
                updated=CURRENT_TIMESTAMP
                """,
                (guild_id, user_id, key, value)
            )

            db.commit()

            self._clean(guild_id, user_id)

    def _clean(self, guild_id, user_id):
        """
        จำกัดจำนวน fact ของ long_memory ต่อ user ไม่ให้เกิน
        config.MAX_LONG_MEMORY_FACTS เพื่อกัน token cost ไหลขึ้นไม่หยุด —
        ถ้าไม่จำกัดไว้ extractor จะสกัด fact ใหม่เพิ่มเรื่อยๆ ทุกข้อความ
        แล้ว _memory_text() ใน ai/context.py จะยัดทุก fact ใส่ทุก request
        ทำให้ baseline token cost ต่อข้อความโตไม่มีเพดานเมื่อใช้งานไปนานๆ

        ลบ fact ที่ "อัปเดตล่าสุดนานสุด" (LRU) ทิ้งก่อน เก็บเฉพาะ
        MAX_LONG_MEMORY_FACTS รายการล่าสุดต่อ guild+user

        เรียกเฉพาะจากภายใน set() ที่ถือ write_lock อยู่แล้วเท่านั้น
        ห้ามเรียกตรงจากข้างนอก ไม่งั้นจะไม่ถูก lock คุ้มครอง
        """

        cur = db.cursor()

        cur.execute(
            """
            DELETE FROM long_memory
            WHERE id NOT IN (
                SELECT id FROM long_memory
                WHERE guild_id=? AND user_id=?
                ORDER BY updated DESC, id DESC
                LIMIT ?
            )
            AND guild_id=? AND user_id=?
            """,
            (
                guild_id, user_id,
                config.MAX_LONG_MEMORY_FACTS,
                guild_id, user_id
            )
        )

        db.commit()

    def get(self, guild_id, user_id):

        cur = db.cursor()

        cur.execute(
            """
            SELECT memory_key, memory_value
            FROM long_memory
            WHERE guild_id=? AND user_id=?
            ORDER BY updated DESC, id DESC
            LIMIT ?
            """,
            (guild_id, user_id, config.MAX_LONG_MEMORY_FACTS)
        )

        return cur.fetchall()


long_memory = LongMemory()