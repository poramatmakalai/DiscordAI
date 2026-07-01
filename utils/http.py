"""
utils/http.py
────────────────────────────────────────────────────────────────────────────
Shared aiohttp.ClientSession แบบ singleton

เดิมทุกจุดที่ยิง HTTP (ดาวน์โหลด attachment, เรียก Ollama, ค้น DuckDuckGo)
สร้าง `aiohttp.ClientSession()` ใหม่ทุกครั้งที่มีข้อความเข้ามา แล้ว async-with
ปิดทิ้งทันที ทำให้ต้องเสียเวลา + resource ตั้ง connector/DNS cache ใหม่ทุก
ครั้งโดยไม่จำเป็น (โดยเฉพาะเวลามีคนแชทถี่ๆ) — ใช้ session เดียวที่เปิดไว้
ตลอดอายุของบอทแทน เพื่อให้ connection pool ถูกใช้ซ้ำ ลด latency ต่อ request

เรียก get_session() เพื่อขอ session (สร้างครั้งแรกแบบ lazy)
เรียก close_session() ตอนบอทปิดตัว (main.py::start())
"""

from __future__ import annotations

import aiohttp

_session: aiohttp.ClientSession | None = None


def get_session() -> aiohttp.ClientSession:
    """คืน ClientSession ที่ใช้ร่วมกันทั้งบอท (สร้างครั้งแรกเมื่อถูกเรียก)"""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_session() -> None:
    """ปิด session ตอนบอทปิดตัว — ป้องกัน 'Unclosed client session' warning"""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None
