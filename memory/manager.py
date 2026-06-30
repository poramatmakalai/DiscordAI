import config
from database.database import db, write_lock


class MemoryManager:

    async def save(self, guild_id, channel_id, user_id, role, content):

        async with write_lock:

            cur = db.cursor()

            cur.execute(
                """
                INSERT INTO memory(
                    guild_id, channel_id, user_id, role, content
                )
                VALUES(?,?,?,?,?)
                """,
                (guild_id, channel_id, user_id, role, content)
            )

            db.commit()

            self._clean(guild_id, channel_id, user_id)

    def _clean(self, guild_id, channel_id, user_id):
        """
        เรียกเฉพาะจากภายใน save() ที่ถือ write_lock อยู่แล้วเท่านั้น
        ห้ามเรียกตรงจากข้างนอก ไม่งั้นจะไม่ถูก lock คุ้มครอง
        """

        cur = db.cursor()

        cur.execute(
            """
            DELETE FROM memory
            WHERE id NOT IN (
                SELECT id FROM memory
                WHERE guild_id=? AND channel_id=? AND user_id=?
                ORDER BY id DESC
                LIMIT ?
            )
            AND guild_id=? AND channel_id=? AND user_id=?
            """,
            (
                guild_id, channel_id, user_id,
                config.MAX_HISTORY,
                guild_id, channel_id, user_id
            )
        )

        db.commit()

    def history(self, guild_id, channel_id, user_id):

        cur = db.cursor()

        cur.execute(
            """
            SELECT role, content
            FROM memory
            WHERE guild_id=? AND channel_id=? AND user_id=?
            ORDER BY id ASC
            """,
            (guild_id, channel_id, user_id)
        )

        return cur.fetchall()


memory = MemoryManager()

