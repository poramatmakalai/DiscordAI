"""
ai/context.py
────────────────────────────────────────────────────────────────────────────
ประกอบ prompt สุดท้ายที่จะส่งให้โมเดล local — ยังคงเป็นแบบ single-turn
(ไม่มีระบบความจำ/ประวัติแชท) เหมือนเดิม แต่ตอนนี้ต้องรวมผลค้นเว็บเป็น
text block ก่อนหน้าข้อความผู้ใช้ เพราะ Ollama chat API รับ message
เป็นข้อความก้อนเดียว ไม่มี "native grounding tool" แนบผลค้นให้อัตโนมัติ
แบบ Gemini
"""

from __future__ import annotations


def build_prompt(
    message_text: str,
    search_block: str | None = None,
) -> str:
    """
    Parameters
    ──────────
    message_text : ข้อความปัจจุบันจากผู้ใช้
    search_block : ผลค้นเว็บที่ format แล้ว (ai.web_search.format_results)
    """
    parts: list[str] = []

    if search_block:
        parts.append(search_block)

    parts.append(message_text or "")

    return "\n\n".join(parts)