import config


def _memory_block(long_memory):

    if not config.ENABLE_LONG_MEMORY:
        return None

    if not long_memory:
        return None

    lines = [
        "# User Memory"
    ]

    for key, value in long_memory:

        lines.append(
            f"{key}: {value}"
        )

    return {
        "role": "user",
        "parts": [
            {
                "text": "\n".join(lines)
            }
        ]
    }


def _search_block(search_result):

    if not config.ENABLE_GOOGLE_SEARCH:
        return None

    if not search_result:
        return None

    return {
        "role": "user",
        "parts": [
            {
                "text":
                "# Google Search\n\n"
                + search_result
            }
        ]
    }


def _file_block(file_summary):

    if not file_summary:
        return None

    return {
        "role": "user",
        "parts": [
            {
                "text":
                "# Uploaded File\n\n"
                + file_summary
            }
        ]
    }


def _vision_block(image_summary):

    if not image_summary:
        return None

    return {
        "role": "user",
        "parts": [
            {
                "text":
                "# Uploaded Image\n\n"
                + image_summary
            }
        ]
    }


def build_contents(

    history,

    long_memory=None,

    search_result=None,

    file_summary=None,

    image_summary=None

):

    contents = []

    # ----------------------------
    # Long Memory
    # ----------------------------

    block = _memory_block(long_memory)

    if block:
        contents.append(block)

    # ----------------------------
    # Google Search
    # ----------------------------

    block = _search_block(search_result)

    if block:
        contents.append(block)

    # ----------------------------
    # File Summary
    # ----------------------------

    block = _file_block(file_summary)

    if block:
        contents.append(block)

    # ----------------------------
    # Image Summary
    # ----------------------------

    block = _vision_block(image_summary)

    if block:
        contents.append(block)

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