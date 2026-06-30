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

    text = clean_response(text)
    text = fix_codeblock(text)

    if len(text) <= DISCORD_LIMIT:
        return [text]

    chunks = []

    while len(text) > DISCORD_LIMIT:

        index = text.rfind("\n", 0, DISCORD_LIMIT)

        if index == -1:
            index = DISCORD_LIMIT

        chunks.append(text[:index])

        text = text[index:]

    if text:
        chunks.append(text)

    return chunks