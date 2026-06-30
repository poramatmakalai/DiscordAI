import config


def _memory_text(long_memory):

    if not config.ENABLE_LONG_MEMORY:
        return None

    if not long_memory:
        return None

    lines = ["# User Memory"]

    for key, value in long_memory:
        lines.append(f"{key}: {value}")

    return "\n".join(lines)


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

    history,

    long_memory=None,

    search_result=None,

    file_summary=None,

    image_summary=None

):

    contents = []

    # ----------------------------
    # รวมบล็อกนำหน้าทั้งหมด (memory / search / file / vision) เป็น
    # "user turn" เดียวแทนที่จะแยกหลาย turn ติดกัน — กัน Gemini สับสน
    # กับการเจอ role="user" ต่อกันหลายครั้งโดยไม่มี "model" คั่น
    # ----------------------------

    lead_blocks = [
        _memory_text(long_memory),
        _search_text(search_result),
        _file_text(file_summary),
        _vision_text(image_summary),
    ]

    lead_blocks = [b for b in lead_blocks if b]

    if lead_blocks:
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": "\n\n".join(lead_blocks)
                    }
                ]
            }
        )

    # ----------------------------
    # Conversation
    # ----------------------------

    for role, content in history:

        if role not in (
            "user",
            "model"
        ):
            continue

        contents.append(
            {
                "role": role,
                "parts": [
                    {
                        "text": content
                    }
                ]
            }
        )

    return contents