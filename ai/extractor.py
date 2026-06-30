"""
ai/extractor.py
────────────────────────────────────────────────────────────────────────────────
Memory Extractor — ดึงข้อมูลสำคัญของผู้ใช้จากบทสนทนา
แล้วบันทึกลง Long Memory (SQLite) อัตโนมัติ

ตัวอย่างสิ่งที่ extract ได้
──────────────────────────
  ชื่อ, อายุ, อาชีพ, ความชอบ, ภาษาที่ใช้, OS, งานที่กำลังทำ ฯลฯ
"""

import json
import logging

import config
from memory.long_memory import long_memory

logger = logging.getLogger(__name__)

# ─── Prompt ────────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """
You are a memory extraction assistant.

Analyze the conversation below and extract any important, reusable facts about the USER only.

Rules:
- Extract facts that are stable and worth remembering long-term.
- Ignore one-time requests or trivial messages.
- Use short, clear keys in English (snake_case).
- Values should be concise.
- Output ONLY a valid JSON object. No explanation, no markdown.
- If there is nothing worth remembering, output exactly: {}

Examples of good keys:
  name, age, occupation, programming_language, os, hobby, location, project

Conversation:
User: {user_message}
Assistant: {ai_reply}

JSON output:
""".strip()


# ─── Extractor ─────────────────────────────────────────────────────────────────

async def extract_and_save(
    guild_id: int,
    user_id: int,
    user_message: str,
    ai_reply: str,
) -> None:
    """
    Extract memorable facts from a single exchange and save to long_memory.

    Parameters
    ──────────
    guild_id     : Discord Guild ID
    user_id      : Discord User ID
    user_message : The user's message text
    ai_reply     : The AI's reply text

    This function is a no-op if ENABLE_MEMORY_EXTRACTOR is False in config.
    All errors are caught and logged — never raises to the caller.
    """

    if not config.ENABLE_MEMORY_EXTRACTOR:
        return

    try:
        # Import lazily to avoid circular imports at module load time
        from ai.gemini import _get_extractor_client

        prompt = _EXTRACT_PROMPT.format(
            user_message=user_message[:1000],
            ai_reply=ai_reply[:1000],
        )

        client = _get_extractor_client()
        raw = await client.async_generate(prompt)

        # ── Parse JSON ────────────────────────────────────────────────────────
        raw = raw.strip()

        # Strip markdown fences if model accidentally wrapped in ```json ... ```
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()

        facts: dict = json.loads(raw)

        if not isinstance(facts, dict) or not facts:
            return

        # ── Save each fact ────────────────────────────────────────────────────
        for key, value in facts.items():
            key   = str(key).strip().lower().replace(" ", "_")[:100]
            value = str(value).strip()[:500]

            if key and value:
                long_memory.set(guild_id, user_id, key, value)
                logger.debug(
                    "[Extractor] guild=%s user=%s  %s = %s",
                    guild_id, user_id, key, value,
                )

        if facts:
            logger.info(
                "[Extractor] Saved %d fact(s) for user %s",
                len(facts), user_id,
            )

    except json.JSONDecodeError:
        logger.debug("[Extractor] Model returned non-JSON — skipping.")
    except Exception as exc:
        logger.warning("[Extractor] Extraction failed: %s", exc)