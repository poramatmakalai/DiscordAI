"""
ai/ollama_client.py
────────────────────────────────────────────────────────────────────────────
Local-only AI client — เรียก Ollama ที่รันอยู่บนเครื่องตัวเอง (localhost)
แทนที่ Gemini API เดิมทั้งหมด ไม่มีการส่ง key หรือส่งข้อมูลออกไปนอกเครื่อง
สำหรับส่วนนี้ (ยกเว้น ai/web_search.py ที่ยิงหา DuckDuckGo แยกต่างหาก)

ก่อนใช้งานต้อง
──────────────
  1) ติดตั้ง Ollama: https://ollama.com/download
  2) รัน `ollama serve` (ปกติจะรันเป็น background service ให้อัตโนมัติ
     หลังติดตั้งอยู่แล้ว)
  3) ดึงโมเดลตามที่ตั้งไว้ใน config.py / .env:
       ollama pull llama3.2:3b
       ollama pull llava-phi3
"""

from __future__ import annotations

import base64
import json
from typing import AsyncGenerator, Optional

import aiohttp

from utils.logger import logger
from utils.http import get_session
import config as _config

try:
    from ai.system_prompt import SYSTEM_PROMPT
except ImportError:
    SYSTEM_PROMPT = None


# ─── Custom Exceptions ────────────────────────────────────────────────────────

class OllamaError(Exception):
    """Base exception สำหรับ error จาก Ollama"""


class OllamaConnectionError(OllamaError):
    """ต่อ Ollama ไม่ได้ — เช็คว่ารัน `ollama serve` อยู่หรือยัง"""


class OllamaResponseError(OllamaError):
    """Ollama ตอบกลับมาแบบผิดปกติ / parse ไม่ได้"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _encode_images(image_bytes_list: Optional[list[bytes]]) -> Optional[list[str]]:
    if not image_bytes_list:
        return None
    return [base64.b64encode(b).decode("ascii") for b in image_bytes_list]


def _select_model(has_images: bool) -> str:
    """ใช้โมเดล vision อัตโนมัติถ้ามีรูปแนบมา ไม่งั้นใช้โมเดลข้อความล้วน"""
    return _config.VISION_MODEL if has_images else _config.TEXT_MODEL


def _build_payload(prompt: str, images: Optional[list[bytes]], stream: bool) -> dict:
    message: dict = {"role": "user", "content": prompt}

    encoded = _encode_images(images)
    if encoded:
        message["images"] = encoded

    messages = []
    if SYSTEM_PROMPT:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.append(message)

    return {
        "model": _select_model(bool(images)),
        "messages": messages,
        "stream": stream,
        # keep_alive: บอก Ollama ให้กันโมเดลค้างอยู่ใน RAM นานเท่านี้หลัง
        # request นี้ (ไม่ใช้ default 5 นาทีของ Ollama เอง) กัน reload
        # โมเดลจากดิสก์ซ้ำๆ ถ้ามีคนแชทถี่กว่านั้น — ลด latency ของข้อความ
        # ถัดๆ ไปได้มากบนเครื่องที่ไม่มีการ์ดจอแยก
        "keep_alive": _config.OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": _config.TEMPERATURE,
            "top_p": _config.TOP_P,
            "top_k": _config.TOP_K,
            "num_predict": _config.MAX_OUTPUT_TOKENS,
            # ระบุ context window ตรงๆ กันโมเดลใช้ค่า default ที่อาจเล็ก
            # เกินไปจน prompt (system prompt + เอกสาร/ผลค้นเว็บ) ถูกตัด
            # ท้ายเงียบๆ หรือใหญ่เกินจำเป็นจนกิน RAM/ช้าลงบน CPU
            "num_ctx": _config.OLLAMA_NUM_CTX,
        },
    }


# ─── Public API ───────────────────────────────────────────────────────────────

async def ask(prompt: str, images: Optional[list[bytes]] = None) -> str:
    """
    ส่ง prompt (+ รูปถ้ามี) ไปหา Ollama local แล้วรอคำตอบเต็มทีเดียว (ไม่ stream)
    """
    payload = _build_payload(prompt, images, stream=False)
    url = f"{_config.OLLAMA_HOST}/api/chat"

    try:
        session = get_session()
        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=300)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise OllamaResponseError(f"Ollama HTTP {resp.status}: {text[:300]}")
            data = await resp.json()
    except aiohttp.ClientConnectorError as exc:
        raise OllamaConnectionError(
            f"ต่อ Ollama ที่ {_config.OLLAMA_HOST} ไม่ได้ — เช็คว่ารัน `ollama serve` อยู่หรือยัง"
        ) from exc
    except OllamaError:
        raise
    except Exception as exc:
        raise OllamaError(f"Ollama request error: {exc}") from exc

    try:
        return data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise OllamaResponseError(f"Ollama response รูปแบบไม่ถูกต้อง: {data}") from exc


async def ask_stream(prompt: str, images: Optional[list[bytes]] = None) -> AsyncGenerator[str, None]:
    """
    เหมือน ask() แต่ yield คำตอบทีละ chunk

    Ollama (เมื่อ stream=true) ส่ง JSON object กลับมาทีละบรรทัด (newline-delimited)
    เช่น {"message": {"role": "assistant", "content": "สวัส"}, "done": false}
    บรรทัดสุดท้ายจะมี "done": true
    """
    payload = _build_payload(prompt, images, stream=True)
    url = f"{_config.OLLAMA_HOST}/api/chat"

    try:
        session = get_session()
        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=300)
        ) as resp:

            if resp.status != 200:
                text = await resp.text()
                raise OllamaResponseError(f"Ollama HTTP {resp.status}: {text[:300]}")

            async for raw_line in resp.content:
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "[Ollama] ข้าม line ที่ parse JSON ไม่ได้: %r", line[:200]
                    )
                    continue

                chunk = obj.get("message", {}).get("content", "")
                if chunk:
                    yield chunk

                if obj.get("done"):
                    break

    except aiohttp.ClientConnectorError as exc:
        raise OllamaConnectionError(
            f"ต่อ Ollama ที่ {_config.OLLAMA_HOST} ไม่ได้ — เช็คว่ารัน `ollama serve` อยู่หรือยัง"
        ) from exc
    except OllamaError:
        raise
    except Exception as exc:
        raise OllamaError(f"Ollama streaming error: {exc}") from exc