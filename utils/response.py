DISCORD_LIMIT = 2000


def split_message(text: str, limit: int = DISCORD_LIMIT):
    """
    แบ่งข้อความให้ไม่เกิน 2000 ตัวอักษร
    """

    if len(text) <= limit:
        return [text]

    messages = []

    while len(text) > limit:

        index = text.rfind("\n", 0, limit)

        if index == -1:
            index = limit

        messages.append(text[:index])

        text = text[index:]

    if text:
        messages.append(text)

    return messages