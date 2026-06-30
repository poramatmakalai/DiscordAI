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

    def get(self, guild_id, user_id):

        cur = db.cursor()

        cur.execute(
            """
            SELECT memory_key, memory_value
            FROM long_memory
            WHERE guild_id=? AND user_id=?
            """,
            (guild_id, user_id)
        )

        return cur.fetchall()


long_memory = LongMemory()

