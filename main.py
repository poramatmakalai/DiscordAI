import asyncio
import os
import tempfile
from pathlib import Path

import discord

import config

from ai.context import build_prompt
from ai.document_reader import extract_text
from ai.ollama_client import ask, ask_stream, OllamaError, OllamaConnectionError
from ai.web_search import search_duckduckgo, format_results, should_search

from utils.logger import logger
from utils.formatter import split_response
from utils.http import get_session, close_session

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


# ──────────────────────────────────────────────────────────────────────────────
# Attachment Helper
# ──────────────────────────────────────────────────────────────────────────────

async def download_attachments(
    attachments: list[discord.Attachment],
    folder: str,
) -> tuple[list[str], list[str], list[str]]:
    """
    ดาวน์โหลด Discord attachments ลง folder ชั่วคราว แยกเป็นรูป/เอกสาร
    Returns (image_paths, document_paths, skipped_names)
    """
    images:    list[str] = []
    documents: list[str] = []
    skipped:   list[str] = []

    # แนบเกินจำนวนที่รองรับ (MAX_ATTACHMENTS) — เดิมโดนตัดทิ้งเงียบๆ โดยไม่มี
    # อะไรแจ้งผู้ใช้เลยว่าไฟล์ท้ายๆ ไม่ถูกประมวลผล ตอนนี้แจ้งใน skipped ด้วย
    accepted   = attachments[:config.MAX_ATTACHMENTS]
    overflow   = attachments[config.MAX_ATTACHMENTS:]
    for att in overflow:
        skipped.append(att.filename)
        logger.debug("[Attach] เกิน MAX_ATTACHMENTS ข้าม: %s", att.filename)

    session = get_session()

    for att in accepted:

        ext = Path(att.filename).suffix.lower()

        is_image    = config.ENABLE_VISION      and ext in config.SUPPORTED_IMAGE_TYPES
        is_document = config.ENABLE_FILE_READER and ext in config.SUPPORTED_DOCUMENTS

        if not (is_image or is_document):
            skipped.append(att.filename)
            logger.debug("[Attach] Unsupported type skipped: %s", att.filename)
            continue

        max_bytes = (
            config.MAX_IMAGE_SIZE_MB if is_image else config.MAX_FILE_SIZE_MB
        ) * 1024 * 1024

        if att.size > max_bytes:
            skipped.append(att.filename)
            logger.warning(
                "[Attach] File too large (%s MB): %s",
                round(att.size / 1024 / 1024, 1),
                att.filename,
            )
            continue

        dest = os.path.join(folder, att.filename)

        try:
            async with session.get(att.url) as resp:
                if resp.status == 200:
                    with open(dest, "wb") as f:
                        f.write(await resp.read())
                    (images if is_image else documents).append(dest)
                    logger.debug("[Attach] Downloaded: %s", att.filename)
                else:
                    skipped.append(att.filename)
                    logger.warning(
                        "[Attach] HTTP %d for %s", resp.status, att.filename
                    )
        except Exception as exc:
            skipped.append(att.filename)
            logger.warning("[Attach] Download failed (%s): %s", att.filename, exc)

    return images, documents, skipped


def _read_image_bytes(paths: list[str]) -> list[bytes]:
    """อ่านรูปเป็น bytes เพื่อเอาไป base64 ส่งให้โมเดล vision ผ่าน Ollama"""
    data: list[bytes] = []
    for p in paths:
        try:
            data.append(Path(p).read_bytes())
        except Exception as exc:
            logger.warning("[Attach] อ่านไฟล์รูป %s ไม่สำเร็จ: %s", p, exc)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Streaming Reply
# ──────────────────────────────────────────────────────────────────────────────

async def send_streaming_reply(
    message: discord.Message,
    prompt: str,
    images: list[bytes] | None = None,
    timeout: float = 120,
) -> str:
    """
    ส่งคำตอบแบบ Streaming — แก้ข้อความทีละ chunk
    ทุก STREAM_EDIT_INTERVAL วินาที เพื่อไม่ให้ hit Discord rate limit

    Timeout และ error ทุกแบบ (ต่อ Ollama ไม่ได้ / ตอบช้าเกินกำหนด / error
    อื่นๆ) ถูกจัดการ "ในนี้" ทั้งหมด แล้ว edit ข้อความ placeholder
    ("⏳ กำลังพิมพ์...") ให้กลายเป็นข้อความ error โดยตรง — เดิมถ้า error
    เกิดขึ้นระหว่าง stream ข้อความ placeholder จะค้างอยู่แบบนั้นตลอดไป
    เพราะ error handler ใน on_message ส่ง reply ใหม่แยกต่างหากแทนที่จะ
    แก้ข้อความเดิม ทำให้ผู้ใช้เห็นข้อความ "กำลังพิมพ์..." ค้างพร้อม error
    แยกอีกอันด้านล่าง

    Returns: full reply string (ว่างถ้า error/timeout — แปลว่าจัดการ
    แจ้งผู้ใช้เรียบร้อยแล้วในฟังก์ชันนี้ ไม่ต้องทำอะไรต่อใน on_message)
    """
    interval  = config.STREAM_EDIT_INTERVAL
    buffer    = ""
    last_edit = asyncio.get_event_loop().time()

    sent = await message.reply("⏳ กำลังพิมพ์...", mention_author=False)

    async def _stream_loop() -> None:
        nonlocal buffer, last_edit

        async for chunk in ask_stream(prompt, images=images):

            buffer += chunk
            now = asyncio.get_event_loop().time()

            if now - last_edit >= interval and buffer.strip():
                preview = buffer
                if len(preview) > config.DISCORD_MESSAGE_LIMIT - 3:
                    preview = preview[:config.DISCORD_MESSAGE_LIMIT - 3] + "..."
                try:
                    await sent.edit(content=preview)
                    last_edit = now
                except discord.HTTPException:
                    pass    # ถ้า rate limit ก็ข้ามไป

    try:
        await asyncio.wait_for(_stream_loop(), timeout=timeout)

    except OllamaConnectionError as e:
        logger.warning("[Ollama] ต่อไม่ได้: %s", e)
        embed = discord.Embed(
            title="⚠️ ต่อโมเดล AI (local) ไม่ได้",
            description=(
                "เช็คว่าเปิด `ollama serve` อยู่บนเครื่องที่รันบอทนี้หรือยัง "
                f"(ตอนนี้ตั้งไว้ที่ `{config.OLLAMA_HOST}`)"
            ),
            color=discord.Color.orange(),
        )
        await sent.edit(content=None, embed=embed)
        return ""

    except OllamaError as e:
        logger.exception(e)
        embed = discord.Embed(
            title="❌ เกิดข้อผิดพลาดกับ AI (local)",
            description="ขออภัยครับ โมเดล local มีปัญหาชั่วคราว กรุณาลองใหม่อีกครั้ง",
            color=discord.Color.red(),
        )
        await sent.edit(content=None, embed=embed)
        return ""

    except asyncio.TimeoutError:
        embed = discord.Embed(
            title="⏰ ใช้เวลานานเกินไป",
            description=(
                "โมเดล local ตอบช้ากว่าที่กำหนดไว้ — ถ้าไม่มีการ์ดจอแยก "
                "โมเดล vision อาจใช้เวลานานเป็นพิเศษ ลองใหม่อีกครั้งครับ"
            ),
            color=discord.Color.orange(),
        )
        try:
            await sent.edit(content=None, embed=embed)
        except discord.HTTPException:
            pass
        return ""

    except Exception as e:
        logger.exception(e)
        embed = discord.Embed(
            title="❌ เกิดข้อผิดพลาด",
            description="ขออภัยครับ เกิดข้อผิดพลาดที่ไม่คาดคิด กรุณาลองใหม่อีกครั้ง",
            color=discord.Color.red(),
        )
        await sent.edit(content=None, embed=embed)
        return ""

    if not buffer.strip():
        await sent.edit(content="❌ โมเดลไม่ได้ส่งคำตอบกลับมา")
        return ""

    parts = split_response(buffer)

    await sent.edit(content=parts[0])

    for part in parts[1:]:
        await message.channel.send(part)

    return buffer


# ──────────────────────────────────────────────────────────────────────────────
# Discord Events
# ──────────────────────────────────────────────────────────────────────────────

@client.event
async def on_ready():
    logger.info(f"Login : {client.user}")
    logger.info(f"Allowed Channels : {config.ALLOWED_CHANNELS}")
    logger.info(f"Streaming : {config.ENABLE_STREAMING}")
    logger.info(f"Ollama Host : {config.OLLAMA_HOST}")
    logger.info(f"Text Model : {config.TEXT_MODEL} | Vision Model : {config.VISION_MODEL}")
    logger.info(
        f"Web Search (DuckDuckGo scrape, no API key) : {config.ENABLE_WEB_SEARCH} "
        f"| Mode : {config.SEARCH_MODE}"
    )
    logger.info(f"Debug : {config.DEBUG}")


@client.event
async def on_message(message):

    if message.author.bot:
        return

    if message.guild is None:
        return

    if message.channel.id not in config.ALLOWED_CHANNELS:
        return

    if not message.content.strip() and not message.attachments:
        return

    if config.DEBUG:
        logger.debug(
            "[DEBUG] %s : %s | attachments=%d",
            message.author.name,
            message.content[:100],
            len(message.attachments),
        )

    async with message.channel.typing():

        tmp_ctx = None

        try:

            image_paths: list[str] = []
            doc_paths:   list[str] = []

            if message.attachments:
                tmp_ctx = tempfile.TemporaryDirectory()
                tmpdir  = tmp_ctx.__enter__()

                image_paths, doc_paths, skipped = await download_attachments(
                    message.attachments, tmpdir
                )

                if skipped:
                    await message.channel.send(
                        f"⚠️ ไฟล์ต่อไปนี้ไม่รองรับหรือใหญ่เกินไป จึงถูกข้าม: "
                        f"`{'`, `'.join(skipped)}`",
                        reference=message,
                    )

            try:
                # ------------------------------------------------------------
                # อ่านไฟล์เอกสารเป็นข้อความ — local ทั้งหมด (ai/document_reader.py)
                # extract_text() เป็น sync/blocking (pypdf, python-docx ทำงาน
                # แบบ CPU-bound) ถ้าเรียกตรงๆ ใน event loop จะบล็อกทั้งบอทไม่
                # ให้ตอบข้อความอื่น/guild อื่นระหว่างที่กำลัง parse ไฟล์อยู่
                # เลยต้องโยนไปรันใน thread แยกผ่าน asyncio.to_thread แทน
                #
                # และรันคู่ขนานไปกับการค้นเว็บ (แทนที่จะรอ search จบก่อนค่อย
                # อ่านไฟล์แบบเดิม) ด้วย asyncio.gather เพื่อลดเวลารวมของทั้ง
                # สองงานที่ไม่ได้พึ่งพากันเลย
                # ------------------------------------------------------------
                async def _extract_docs() -> list[str]:
                    texts = await asyncio.gather(
                        *(asyncio.to_thread(extract_text, p) for p in doc_paths)
                    )
                    return [
                        f"[ไฟล์แนบ: {Path(p).name}]\n{t}"
                        for p, t in zip(doc_paths, texts)
                        if t
                    ]

                # ------------------------------------------------------------
                # ค้นเว็บผ่าน DuckDuckGo (ไม่ใช้ API key แต่ยังต่อเน็ตอยู่)
                # ปิดได้ที่ config.ENABLE_WEB_SEARCH = False
                #
                # SEARCH_MODE == "auto" (ค่า default): ข้ามการค้นเว็บสำหรับ
                # ข้อความที่ดูไม่จำเป็นต้องใช้ข้อมูลภายนอก (เช่น ทักทาย/ขอ
                # โค้ด/คุยเล่น) ตัด network round-trip + parse HTML ทิ้งไป
                # ในเคสส่วนใหญ่ → ตอบเร็วขึ้นชัดเจน ตั้งเป็น "always" ใน
                # config.py ได้ถ้าอยากค้นทุกข้อความเหมือนพฤติกรรมเดิม
                # ------------------------------------------------------------
                async def _web_search() -> str:
                    text = message.content.strip()
                    if not (config.ENABLE_WEB_SEARCH and text):
                        return ""
                    if config.SEARCH_MODE == "auto" and not should_search(text):
                        return ""
                    results = await search_duckduckgo(text, config.SEARCH_MAX_RESULTS)
                    return format_results(results)

                doc_blocks, search_block = await asyncio.gather(
                    _extract_docs(), _web_search()
                )

                prompt = build_prompt(
                    message.content,
                    doc_blocks=doc_blocks,
                    search_block=search_block,
                )

                image_bytes = _read_image_bytes(image_paths) if image_paths else None

                # โมเดล local บน CPU (ไม่มีการ์ดจอแยก) ช้ากว่า cloud API มาก
                # โดยเฉพาะโมเดล vision — ให้เวลามากขึ้น
                timeout = 180 if image_bytes else 120

                if config.ENABLE_STREAMING:
                    # send_streaming_reply จัดการ timeout/error ของตัวเอง
                    # ทั้งหมดแล้ว (ดูคอมเมนต์ในฟังก์ชัน) ไม่ต้อง wrap
                    # asyncio.wait_for ซ้ำอีกชั้นตรงนี้
                    reply = await send_streaming_reply(
                        message, prompt, images=image_bytes, timeout=timeout
                    )
                else:
                    reply = await asyncio.wait_for(
                        ask(prompt, images=image_bytes),
                        timeout=timeout,
                    )

            finally:
                # cleanup temp dir — ต้องอยู่ใน finally เสมอ ไม่งั้นถ้า ask()/
                # ask_stream() โยน exception ออกมา (timeout, OllamaError ฯลฯ)
                # ไฟล์แนบที่ดาวน์โหลดไว้จะค้างอยู่ในดิสก์ตลอดไป (resource leak)
                if tmp_ctx:
                    tmp_ctx.__exit__(None, None, None)

            if not reply:
                return

            logger.info(
                f"{message.author} | {len(reply)} chars | "
                f"attachments={len(message.attachments)} | "
                f"streaming={config.ENABLE_STREAMING}"
            )

            if not config.ENABLE_STREAMING:

                for i, part in enumerate(split_response(reply)):

                    if i == 0:
                        await message.reply(part, mention_author=False)
                    else:
                        await message.channel.send(part)

        except OllamaConnectionError as e:

            logger.warning("[Ollama] ต่อไม่ได้: %s", e)

            embed = discord.Embed(
                title="⚠️ ต่อโมเดล AI (local) ไม่ได้",
                description=(
                    "เช็คว่าเปิด `ollama serve` อยู่บนเครื่องที่รันบอทนี้หรือยัง "
                    f"(ตอนนี้ตั้งไว้ที่ `{config.OLLAMA_HOST}`)"
                ),
                color=discord.Color.orange(),
            )

            await message.reply(embed=embed, mention_author=False)

        except OllamaError as e:

            logger.exception(e)

            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาดกับ AI (local)",
                description="ขออภัยครับ โมเดล local มีปัญหาชั่วคราว กรุณาลองใหม่อีกครั้ง",
                color=discord.Color.red(),
            )

            await message.reply(embed=embed, mention_author=False)

        except asyncio.TimeoutError:

            embed = discord.Embed(
                title="⏰ ใช้เวลานานเกินไป",
                description=(
                    "โมเดล local ตอบช้ากว่าที่กำหนดไว้ — ถ้าไม่มีการ์ดจอแยก "
                    "โมเดล vision อาจใช้เวลานานเป็นพิเศษ ลองใหม่อีกครั้งครับ"
                ),
                color=discord.Color.orange(),
            )

            await message.reply(embed=embed, mention_author=False)

        except Exception as e:

            logger.exception(e)

            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description="ขออภัยครับ เกิดข้อผิดพลาดที่ไม่คาดคิด กรุณาลองใหม่อีกครั้ง",
                color=discord.Color.red(),
            )

            await message.reply(embed=embed, mention_author=False)


# ──────────────────────────────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────────────────────────────

async def start():
    try:
        async with client:
            await client.start(config.DISCORD_TOKEN)
    finally:
        # ปิด shared aiohttp session ตอนบอทปิดตัว กัน 'Unclosed client
        # session' warning และคืน connection pool ให้เรียบร้อย
        await close_session()


if __name__ == "__main__":
    asyncio.run(start())