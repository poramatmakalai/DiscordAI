"""
ai/document_reader.py
────────────────────────────────────────────────────────────────────────────
อ่านไฟล์เอกสารที่แนบมาแล้วแปลงเป็นข้อความล้วนๆ — ทำงานแบบ local ทั้งหมด
ไม่มีการอัปโหลด/ส่งไฟล์ออกไปที่ไหนเลย (ต่างจาก Gemini เดิมที่ส่ง PDF เป็น
inline blob ไปให้ Google ประมวลผลฝั่งเซิร์ฟเวอร์)

ข้อความที่ extract ได้จะถูกแปะเป็น context ข้อความธรรมดาก่อนคำถามผู้ใช้
แล้วส่งเข้าโมเดล local ทั้งก้อน (ดู ai/context.py::build_prompt)
"""

from __future__ import annotations

import json
from pathlib import Path

# กันเนื้อหายาวเกินจน context window ของโมเดล local ล้น (โมเดลเล็กบน CPU
# มักมี context window แคบกว่า Gemini มาก)
MAX_CHARS = 6000


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS] + f"\n...[ตัดเนื้อหาเพราะยาวเกิน {MAX_CHARS} ตัวอักษร]"


def _read_txt(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _read_csv(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _read_json(path: str) -> str:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return json.dumps(raw, ensure_ascii=False, indent=2)


def _read_docx(path: str) -> str:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "python-docx ยังไม่ได้ติดตั้ง — รัน: pip install python-docx"
        ) from exc

    doc = Document(path)
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(lines)


def _read_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pypdf ยังไม่ได้ติดตั้ง — รัน: pip install pypdf"
        ) from exc

    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    return "\n\n".join(pages)


_READERS = {
    ".txt":  _read_txt,
    ".csv":  _read_csv,
    ".json": _read_json,
    ".docx": _read_docx,
    ".pdf":  _read_pdf,
}


def extract_text(path: str) -> str:
    """
    แปลงไฟล์เอกสารเป็นข้อความล้วน (เลือกวิธีอ่านจากนามสกุลไฟล์)

    คืนค่า string ว่างถ้าไม่รู้จักนามสกุล และคืนข้อความ error แบบสั้นๆ
    (ไม่ raise) ถ้าอ่านไฟล์ไม่สำเร็จ — กันไม่ให้ทั้งข้อความพังเพราะไฟล์
    แนบไฟล์เดียวมีปัญหา
    """
    ext = Path(path).suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        return ""

    try:
        text = reader(path)
    except Exception as exc:
        return f"[อ่านไฟล์ {Path(path).name} ไม่สำเร็จ: {exc}]"

    return _truncate(text.strip())
