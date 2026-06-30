def build_contents(message_text):
    """
    สร้าง contents สำหรับ Gemini แบบ single-turn (ไม่มีระบบความจำ/ประวัติแชท
    อีกต่อไป) — แต่ละข้อความที่ผู้ใช้ส่งมาจะถูกส่งให้ AI แบบแยกอิสระ
    ไม่มี context จากข้อความก่อนหน้า

    หมายเหตุ: Google Search ใช้ native grounding tool ของ Gemini
    (ดู ai/gemini.py::_build_config) และไฟล์/รูปภาพแนบถูกแปลงเป็น
    Part ส่งตรงผ่านพารามิเตอร์ files= ใน ask()/ask_stream() อยู่แล้ว
    จึงไม่ต้องประกอบเป็น text block ที่นี่

    Parameters
    ──────────
    message_text  : ข้อความปัจจุบันจากผู้ใช้ (str)
    """

    return [
        {"role": "user", "parts": [{"text": message_text}]}
    ]