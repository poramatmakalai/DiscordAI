import config


def _search_text(search_result):

    if not config.ENABLE_GOOGLE_SEARCH:
        return None

    if not search_result:
        return None

    return "# Google Search\n\n" + search_result


def _file_text(file_summary):

    if not file_summary:
        return None

    return "# Uploaded File\n\n" + file_summary


def _vision_text(image_summary):

    if not image_summary:
        return None

    return "# Uploaded Image\n\n" + image_summary


def build_contents(

    message_text,

    search_result=None,

    file_summary=None,

    image_summary=None

):
    """
    สร้าง contents สำหรับ Gemini แบบ single-turn (ไม่มีระบบความจำ/ประวัติแชท
    อีกต่อไป) — แต่ละข้อความที่ผู้ใช้ส่งมาจะถูกส่งให้ AI แบบแยกอิสระ
    ไม่มี context จากข้อความก่อนหน้า

    Parameters
    ──────────
    message_text  : ข้อความปัจจุบันจากผู้ใช้ (str)
    search_result : ผลลัพธ์จาก Google Search (ถ้าเปิดใช้งาน)
    file_summary  : เนื้อหาที่สกัดจากไฟล์แนบ (ถ้ามี)
    image_summary : คำอธิบาย/บริบทของรูปภาพแนบ (ถ้ามี)
    """

    lead_blocks = [
        _search_text(search_result),
        _file_text(file_summary),
        _vision_text(image_summary),
    ]

    lead_blocks = [b for b in lead_blocks if b]

    parts = lead_blocks + [message_text]

    text = "\n\n".join(parts)

    return [
        {"role": "user", "parts": [{"text": text}]}
    ]