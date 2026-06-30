from database.database import db


MAX_MEMORY = 30


class MemoryManager:

    def save(self, guild_id, channel_id, user_id, role, content):

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

        self.clean(guild_id, channel_id, user_id)

    def clean(self, guild_id, channel_id, user_id):

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
                MAX_MEMORY,
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
