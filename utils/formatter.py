import re

DISCORD_LIMIT = 2000


def clean_response(text: str) -> str:
    """
    ทำความสะอาดข้อความก่อนส่ง Discord
    """

    text = text.replace("\r\n", "\n")
    text = text.strip()

    return text


def fix_codeblock(text: str) -> str:
    """
    ปิด ``` ถ้า AI ลืมปิด
    """

    if text.count("```") % 2 != 0:
        text += "\n```"

    return text


def split_response(text: str):
    """
    แบ่งข้อความให้ไม่เกิน DISCORD_LIMIT ตัวอักษร

    ถ้าจุดตัดอยู่กลาง code block (```...```) จะปิด ``` ให้ใน chunk นั้น
    แล้วเปิด ``` ใหม่ให้ใน chunk ถัดไปอัตโนมัติ กัน backtick ค้าง/เพี้ยน
    เวลาข้อความยาวถูกตัดแบ่งหลายข้อความ
    """

    text = clean_response(text)
    text = fix_codeblock(text)

    if len(text) <= DISCORD_LIMIT:
        return [text]

    chunks: list[str] = []
    in_code_block = False
    # ภาษาของ code block ปัจจุบัน (เช่น "python") เก็บไว้เผื่อต้องเปิดใหม่
    current_lang = ""

    while len(text) > DISCORD_LIMIT:

        # เผื่อที่ไว้สำหรับปิด/เปิด ``` ในแต่ละ chunk (กันเกิน limit)
        budget = DISCORD_LIMIT - 4

        index = text.rfind("\n", 0, budget)
        if index == -1:
            index = budget

        chunk = text[:index]
        rest  = text[index:]

        # นับจำนวน ``` ใน chunk นี้ เพื่ออัปเดตสถานะว่าอยู่ในบล็อกโค้ดไหม
        fence_count = chunk.count("```")

        # ดึงชื่อภาษาจาก ``` ตัวล่าสุดที่ "เปิด" บล็อกใน chunk นี้ (ถ้ามี)
        opens = list(re.finditer(r"```([^\n`]*)\n?", chunk))
        was_in_block = in_code_block

        if fence_count % 2 != 0:
            in_code_block = not in_code_block
            if in_code_block and opens:
                current_lang = opens[-1].group(1).strip()
            if not in_code_block:
                current_lang = ""

        if in_code_block:
            # ตัดกลางบล็อกโค้ด → ปิด ``` ให้จบ chunk นี้
            chunk += "\n```"

        chunks.append(chunk)

        if in_code_block:
            # เปิด ``` ใหม่ให้ chunk ถัดไป (คง syntax highlight เดิมไว้)
            fence = f"```{current_lang}\n" if current_lang else "```\n"
            rest = fence + rest

        text = rest

    if text:
        chunks.append(text)

    return chunks