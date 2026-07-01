"""
ai/web_search.py
────────────────────────────────────────────────────────────────────────────
ค้นเว็บแบบไม่ใช้ API key ใดๆ — scrape หน้า HTML ของ DuckDuckGo
(html.duckduckgo.com) ซึ่งเป็น endpoint แบบไม่มี JavaScript ที่ DuckDuckGo
เปิดให้ browser ที่ไม่รองรับ JS ใช้อยู่แล้ว ไม่ต้องสมัคร ไม่ต้องมี key

⚠️ หมายเหตุสำคัญ: ฟีเจอร์นี้เป็นจุดเดียวในทั้งบอทที่ยังต่อเน็ตออกไปหาที่อื่น
(นอกจาก Discord เอง) — ถ้าต้องการบอทที่ไม่ต่อเน็ตออกไปไหนเลยจริงๆ ให้ปิด
ผ่าน config.ENABLE_WEB_SEARCH = False
"""

from __future__ import annotations

import re
from typing import TypedDict

import aiohttp
from bs4 import BeautifulSoup

from utils.logger import logger
from utils.http import get_session

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# คำ/รูปแบบที่บ่งชี้ว่าข้อความน่าจะต้องใช้ข้อมูลล่าสุด/ภายนอกจริงๆ
# ใช้ตอน config.SEARCH_MODE == "auto" เพื่อข้ามการค้นเว็บทิ้งสำหรับข้อความ
# ทั่วไป (ทักทาย, ขอโค้ด, คุยเล่น ฯลฯ) ที่ไม่ได้ต้องการข้อมูลภายนอกจริงๆ
_TRIGGER_WORDS = (
    "ล่าสุด", "วันนี้", "ตอนนี้", "ข่าว", "ราคา", "อัปเดต", "อัพเดท",
    "เมื่อไหร่", "เมื่อไร", "กี่โมง", "search", "latest", "news", "price",
    "today", "current", "update",
)
_URL_RE = re.compile(r"https?://\S+")


class SearchResult(TypedDict):
    title: str
    snippet: str
    url: str


def should_search(text: str) -> bool:
    """
    Heuristic ง่ายๆ ว่าข้อความนี้ควรค้นเว็บไหม (ใช้เมื่อ config.SEARCH_MODE
    == "auto") — เช็คว่ามีเครื่องหมายคำถาม, มีคำที่บ่งชี้ข้อมูลล่าสุด,
    หรือมี URL แนบมาหรือเปล่า ถ้าไม่เข้าเงื่อนไขไหนเลยถือว่าไม่จำเป็นต้อง
    เสียเวลา round-trip ไป DuckDuckGo
    """
    if not text:
        return False

    if "?" in text or "ไหม" in text or "หรือไม่" in text:
        return True

    lowered = text.lower()
    if any(word in text or word in lowered for word in _TRIGGER_WORDS):
        return True

    if _URL_RE.search(text):
        return True

    return False


async def search_duckduckgo(query: str, max_results: int = 3) -> list[SearchResult]:
    """
    ค้นหาผ่าน DuckDuckGo HTML endpoint แล้ว parse ผลลัพธ์ด้วย BeautifulSoup

    คืน list ว่างเสมอถ้าค้นไม่สำเร็จ (เน็ตหลุด / โครงสร้าง HTML ของ
    DuckDuckGo เปลี่ยน) เพื่อไม่ให้ทั้งบอทพังเพราะ search ล้มเหลว — แค่ตอบ
    โดยไม่มีผลค้นเว็บประกอบแทน
    """
    try:
        session = get_session()
        async with session.post(
            _SEARCH_URL,
            data={"q": query},
            headers=_HEADERS,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                logger.warning("[WebSearch] DuckDuckGo HTTP %d", resp.status)
                return []
            html = await resp.text()
    except Exception as exc:
        logger.warning("[WebSearch] ค้นหาไม่สำเร็จ: %s", exc)
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []

        for result_div in soup.select("div.result")[:max_results]:
            title_tag = result_div.select_one("a.result__a")
            snippet_tag = (
                result_div.select_one("a.result__snippet")
                or result_div.select_one(".result__snippet")
            )

            if not title_tag:
                continue

            results.append(
                {
                    "title": title_tag.get_text(strip=True),
                    "url": title_tag.get("href", ""),
                    "snippet": snippet_tag.get_text(strip=True) if snippet_tag else "",
                }
            )

        return results
    except Exception as exc:
        logger.warning("[WebSearch] parse ผลลัพธ์ไม่สำเร็จ: %s", exc)
        return []


def format_results(results: list[SearchResult]) -> str:
    """แปลง search results เป็น text block เอาไปแปะในบริบทให้โมเดลก่อนคำถามผู้ใช้"""
    if not results:
        return ""

    lines = ["[ผลการค้นหาเว็บล่าสุด — DuckDuckGo]"]
    for i, r in enumerate(results, start=1):
        lines.append(f"{i}. {r['title']}\n   {r['snippet']}\n   ที่มา: {r['url']}")

    return "\n".join(lines)