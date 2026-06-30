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
    lead_text = "\n\n".join(lead_blocks) if lead_blocks else None

    # ----------------------------
    # Conversation
    # ----------------------------

    history = [
        (role, content) for role, content in history
        if role in ("user", "model")
    ]

    if lead_text:
        if history and history[0][0] == "user":
            # ----------------------------
            # ถ้าเทิร์นแรกของ history เป็น "user" อยู่แล้ว ให้รวม
            # lead_blocks เข้าไปในเทิร์นเดียวกันแทนที่จะแทรกเป็น
            # Content แยกต่างหาก — กัน Gemini เจอ role="user" ติดกัน
            # สอง turn รวด ซึ่งไม่ใช่รูปแบบ multi-turn ที่ถูกต้อง
            # ----------------------------
            first_role, first_content = history[0]
            merged = f"{lead_text}\n\n{first_content}"
            contents.append(
                {"role": first_role, "parts": [{"text": merged}]}
            )
            history = history[1:]
        else:
            contents.append(
                {"role": "user", "parts": [{"text": lead_text}]}
            )

    for role, content in history:
        contents.append(
            {"role": role, "parts": [{"text": content}]}
        )

    return contents