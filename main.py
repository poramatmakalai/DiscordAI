import asyncio
import os
import tempfile
from pathlib import Path

import discord
import aiohttp

import config

from ai.context import build_prompt
from ai.document_reader import extract_text
from ai.ollama_client import ask, ask_stream, OllamaError, OllamaConnectionError
from ai.web_search import search_duckduckgo, format_results

from utils.logger import logger
from utils.formatter import split_response

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

    async with aiohttp.ClientSession() as session:

        for att in attachments[:config.MAX_ATTACHMENTS]:

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
) -> str:
    """
    ส่งคำตอบแบบ Streaming — แก้ข้อความทีละ chunk
    ทุก STREAM_EDIT_INTERVAL วินาที เพื่อไม่ให้ hit Discord rate limit

    Returns: full reply string
    """
    interval  = config.STREAM_EDIT_INTERVAL
    buffer    = ""
    last_edit = asyncio.get_event_loop().time()

    sent = await message.reply("⏳ กำลังพิมพ์...", mention_author=False)

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
    logger.info(f"Web Search (DuckDuckGo scrape, no API key) : {config.ENABLE_WEB_SEARCH}")
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
                # ------------------------------------------------------------
                doc_blocks = [
                    f"[ไฟล์แนบ: {Path(p).name}]\n{extract_text(p)}"
                    for p in doc_paths
                    if extract_text(p)
                ]

                # ------------------------------------------------------------
                # ค้นเว็บผ่าน DuckDuckGo (ไม่ใช้ API key แต่ยังต่อเน็ตอยู่)
                # ปิดได้ที่ config.ENABLE_WEB_SEARCH = False
                # ------------------------------------------------------------
                search_block = ""
                if config.ENABLE_WEB_SEARCH and message.content.strip():
                    results = await search_duckduckgo(
                        message.content.strip(), config.SEARCH_MAX_RESULTS
                    )
                    search_block = format_results(results)

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
                    reply = await asyncio.wait_for(
                        send_streaming_reply(message, prompt, images=image_bytes),
                        timeout=timeout,
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
    async with client:
        await client.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(start())