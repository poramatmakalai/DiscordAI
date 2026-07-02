import asyncio

import discord

import config

from ai.context import build_prompt
from ai.ollama_client import ask, ask_stream, OllamaError, OllamaConnectionError
from ai.web_search import search_duckduckgo, format_results, should_search

from utils.logger import logger
from utils.formatter import split_response
from utils.http import close_session

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


# ──────────────────────────────────────────────────────────────────────────────
# Streaming Reply
# ──────────────────────────────────────────────────────────────────────────────

async def send_streaming_reply(
    message: discord.Message,
    prompt: str,
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

        async for chunk in ask_stream(prompt):

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
                "อาจใช้เวลานานเป็นพิเศษ ลองใหม่อีกครั้งครับ"
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
    logger.info(f"Text Model : {config.TEXT_MODEL}")
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

    if not message.content.strip():
        return

    if config.DEBUG:
        logger.debug(
            "[DEBUG] %s : %s",
            message.author.name,
            message.content[:100],
        )

    async with message.channel.typing():

        try:

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
            search_block = ""
            text = message.content.strip()
            if config.ENABLE_WEB_SEARCH and text:
                if config.SEARCH_MODE != "auto" or should_search(text):
                    results = await search_duckduckgo(text, config.SEARCH_MAX_RESULTS)
                    search_block = format_results(results)

            prompt = build_prompt(message.content, search_block=search_block)

            timeout = 120

            if config.ENABLE_STREAMING:
                # send_streaming_reply จัดการ timeout/error ของตัวเอง
                # ทั้งหมดแล้ว (ดูคอมเมนต์ในฟังก์ชัน) ไม่ต้อง wrap
                # asyncio.wait_for ซ้ำอีกชั้นตรงนี้
                reply = await send_streaming_reply(
                    message, prompt, timeout=timeout
                )
            else:
                reply = await asyncio.wait_for(
                    ask(prompt),
                    timeout=timeout,
                )

            if not reply:
                return

            logger.info(
                f"{message.author} | {len(reply)} chars | "
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
                    "โมเดล local ตอบช้ากว่าที่กำหนดไว้ ลองใหม่อีกครั้งครับ"
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