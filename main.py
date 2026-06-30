import asyncio
import os
import tempfile
from pathlib import Path

import discord
import aiohttp

import config

from memory.manager import memory
from memory.long_memory import long_memory
from ai.context import build_contents
from ai.gemini import ask, ask_stream          # ← เพิ่ม ask_stream
from ai.gemini import GeminiRetryExhausted, GeminiError
from ai.extractor import extract_and_save

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
) -> tuple[list[str], list[str]]:
    """
    ดาวน์โหลด Discord attachments ลง folder ชั่วคราว
    Returns (downloaded_paths, skipped_names)
    """
    downloaded: list[str] = []
    skipped:    list[str] = []

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
                        downloaded.append(dest)
                        logger.debug("[Attach] Downloaded: %s", att.filename)
                    else:
                        skipped.append(att.filename)
                        logger.warning(
                            "[Attach] HTTP %d for %s", resp.status, att.filename
                        )
            except Exception as exc:
                skipped.append(att.filename)
                logger.warning("[Attach] Download failed (%s): %s", att.filename, exc)

    return downloaded, skipped


# ──────────────────────────────────────────────────────────────────────────────
# Streaming Reply
# ──────────────────────────────────────────────────────────────────────────────

async def send_streaming_reply(
    message: discord.Message,
    contents: list,
    files: list | None = None,
) -> str:
    """
    ส่งคำตอบแบบ Streaming — แก้ข้อความทีละ chunk
    ทุก STREAM_EDIT_INTERVAL วินาที เพื่อไม่ให้ hit Discord rate limit

    Returns: full reply string
    """
    interval  = config.STREAM_EDIT_INTERVAL
    buffer    = ""
    last_edit = asyncio.get_event_loop().time()

    # ส่งข้อความ placeholder ก่อน
    sent = await message.reply("⏳ กำลังพิมพ์...", mention_author=False)

    async for chunk in ask_stream(contents, files=files):

        buffer += chunk
        now = asyncio.get_event_loop().time()

        # แก้ข้อความทุก interval วินาที
        if now - last_edit >= interval and buffer.strip():
            preview = buffer
            if len(preview) > config.DISCORD_MESSAGE_LIMIT - 3:
                preview = preview[:config.DISCORD_MESSAGE_LIMIT - 3] + "..."
            try:
                await sent.edit(content=preview)
                last_edit = now
            except discord.HTTPException:
                pass    # ถ้า rate limit ก็ข้ามไป

    # ── Final ─────────────────────────────────────────────────────────────────

    if not buffer.strip():
        await sent.edit(content="❌ AI ไม่ได้ส่งคำตอบกลับมา")
        return ""

    parts = split_response(buffer)

    # แก้ข้อความแรก
    await sent.edit(content=parts[0])

    # ส่วนที่เกิน 2000 ตัวอักษรส่งเป็นข้อความใหม่
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
    logger.info(f"Debug : {config.DEBUG}")


@client.event
async def on_message(message):

    # ไม่ตอบ Bot
    if message.author.bot:
        return

    # ไม่ตอบ DM
    if message.guild is None:
        return

    # ตอบเฉพาะห้องที่กำหนด
    if message.channel.id not in config.ALLOWED_CHANNELS:
        return

    # ข้อความว่างและไม่มีไฟล์แนบ
    if not message.content.strip() and not message.attachments:
        return

    # Debug mode: log ทุกข้อความ
    if config.DEBUG:
        logger.debug(
            "[DEBUG] %s : %s | attachments=%d",
            message.author.name,
            message.content[:100],
            len(message.attachments),
        )

    async with message.channel.typing():

        try:

            guild_id   = message.guild.id
            channel_id = message.channel.id
            user_id    = message.author.id

            # ------------------------------------------------------------------
            # Save User Message
            # ------------------------------------------------------------------

            memory.save(
                guild_id,
                channel_id,
                user_id,
                "user",
                message.content or "[ส่งไฟล์แนบ]",
            )

            # ------------------------------------------------------------------
            # History + Long Memory
            # ------------------------------------------------------------------

            history = memory.history(guild_id, channel_id, user_id)

            user_long_memory = long_memory.get(guild_id, user_id)

            contents = build_contents(
                history,
                long_memory=user_long_memory if config.ENABLE_LONG_MEMORY else None,
            )

            # ------------------------------------------------------------------
            # Download Attachments (Vision + File Reader)
            # ------------------------------------------------------------------

            reply: str
            attached_files: list | None = None
            tmp_ctx = None

            if message.attachments:

                tmp_ctx = tempfile.TemporaryDirectory()
                tmpdir  = tmp_ctx.__enter__()

                attached_files, skipped = await download_attachments(
                    message.attachments, tmpdir
                )

                if skipped:
                    await message.channel.send(
                        f"⚠️ ไฟล์ต่อไปนี้ไม่รองรับหรือใหญ่เกินไป จึงถูกข้าม: "
                        f"`{'`, `'.join(skipped)}`",
                        reference=message,
                    )

            # ------------------------------------------------------------------
            # Generate Reply
            # ------------------------------------------------------------------

            timeout = 90 if message.attachments else 60

            if config.ENABLE_STREAMING:

                # ── Streaming mode ─────────────────────────────────────────────
                reply = await asyncio.wait_for(
                    send_streaming_reply(
                        message,
                        contents,
                        files=attached_files or None,
                    ),
                    timeout=timeout,
                )

            else:

                # ── Normal mode ────────────────────────────────────────────────
                reply = await asyncio.wait_for(
                    ask(contents, files=attached_files or None),
                    timeout=timeout,
                )

            # cleanup temp dir
            if tmp_ctx:
                tmp_ctx.__exit__(None, None, None)

            if not reply:
                return

            # ------------------------------------------------------------------
            # Save Model Reply
            # ------------------------------------------------------------------

            memory.save(
                guild_id,
                channel_id,
                user_id,
                "model",
                reply,
            )

            logger.info(
                f"{message.author} | {len(reply)} chars | "
                f"attachments={len(message.attachments)} | "
                f"streaming={config.ENABLE_STREAMING}"
            )

            # ------------------------------------------------------------------
            # Extract Long Memory (background)
            # ------------------------------------------------------------------

            if config.ENABLE_MEMORY_EXTRACTOR:
                asyncio.create_task(
                    extract_and_save(
                        guild_id,
                        user_id,
                        message.content or "[ไฟล์แนบ]",
                        reply,
                    )
                )

            # ------------------------------------------------------------------
            # Send Reply (Normal mode — Streaming ส่งไปแล้วใน send_streaming_reply)
            # ------------------------------------------------------------------

            if not config.ENABLE_STREAMING:

                for i, part in enumerate(split_response(reply)):

                    if i == 0:
                        await message.reply(part, mention_author=False)
                    else:
                        await message.channel.send(part)

        except GeminiRetryExhausted as e:

            logger.warning(
                "[Gemini] Quota exhausted for user %s | detail: %s",
                message.author.id, e,
            )

            embed = discord.Embed(
                title="⚠️ ระบบ AI ไม่ว่างชั่วคราว",
                description=(
                    "ตอนนี้มีคนใช้งานเยอะจนเกินโควต้าฟรีที่กำหนดไว้ในแต่ละวัน 🙏\n"
                    "กรุณาลองใหม่อีกครั้งในภายหลัง หรือลองใหม่พรุ่งนี้นะครับ"
                ),
                color=discord.Color.orange(),
            )
            embed.set_footer(text="โควต้าจะรีเซ็ตใหม่ทุกวัน")

            await message.reply(embed=embed, mention_author=False)

        except GeminiError as e:

            error_text = str(e).lower()
            is_quota_error = (
                "429" in error_text
                or "resource_exhausted" in error_text
                or "quota" in error_text
            )

            if is_quota_error:

                logger.warning(
                    "[Gemini] Quota exhausted (streaming) for user %s | detail: %s",
                    message.author.id, e,
                )

                embed = discord.Embed(
                    title="⚠️ ระบบ AI ไม่ว่างชั่วคราว",
                    description=(
                        "ตอนนี้มีคนใช้งานเยอะจนเกินโควต้าฟรีที่กำหนดไว้ในแต่ละวัน 🙏\n"
                        "กรุณาลองใหม่อีกครั้งในภายหลัง หรือลองใหม่พรุ่งนี้นะครับ"
                    ),
                    color=discord.Color.orange(),
                )
                embed.set_footer(text="โควต้าจะรีเซ็ตใหม่ทุกวัน")

            else:

                logger.exception(e)

                embed = discord.Embed(
                    title="❌ เกิดข้อผิดพลาดกับระบบ AI",
                    description="ขออภัยครับ ระบบ AI มีปัญหาชั่วคราว กรุณาลองใหม่อีกครั้ง",
                    color=discord.Color.red(),
                )

            await message.reply(embed=embed, mention_author=False)

        except asyncio.TimeoutError:

            embed = discord.Embed(
                title="⏰ ใช้เวลานานเกินไป",
                description="AI ใช้เวลาตอบนานเกินไป กรุณาลองใหม่อีกครั้งครับ",
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