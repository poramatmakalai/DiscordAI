"""
ai/gemini.py
────────────────────────────────────────────────────────────────────────────────
Gemini AI wrapper — google-genai SDK 2.10.0

Features
────────
  💬  Text generation
  📷  Image input  (.jpg / .jpeg / .png / .gif / .webp / .bmp)
  📄  PDF input
  📄  DOCX input   (requires: pip install python-docx)
  📄  TXT / CSV / JSON input
  🌐  Google Search grounding
  🧠  System Instruction
  ⚡  Streaming  (sync generator + async generator)
  🔄  Async generation
  🔁  Retry with exponential back-off
  🛡  Structured error handling

Install
────────
  pip install google-genai==2.10.0
  pip install python-docx          # optional – only for .docx

Usage (quick start)
────────────────────
  from ai.gemini import GeminiClient

  client = GeminiClient(
      api_key="YOUR_API_KEY",
      system_instruction="You are a helpful assistant.",
  )

  # Text
  print(client.chat("Hello!"))

  # Image
  print(client.with_image("Describe this image", "photo.jpg"))

  # PDF
  print(client.with_pdf("Summarize this document", "report.pdf"))

  # Google Search
  print(client.search("Latest AI news today"))

  # Streaming
  for chunk in client.stream("Tell me a long story"):
      print(chunk, end="", flush=True)

  # Async
  import asyncio
  result = asyncio.run(client.async_generate("Hello async!"))
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Generator, Optional, Union

from google import genai
from google.genai import types

# ─── Logger ───────────────────────────────────────────────────────────────────
#
# สำคัญ: ต้องใช้ logger ตัวเดียวกับ utils/logger.py (ชื่อ "DiscordAI") ห้ามใช้
# logging.getLogger(__name__) เฉยๆ เพราะ __name__ ในไฟล์นี้จะกลายเป็น
# "ai.gemini" ซึ่งไม่มี handler (file + console) ผูกอยู่เลย — ผลคือ log
# ทุกบรรทัดในไฟล์นี้ (retry warning, quota exhausted, debug โหลดไฟล์ ฯลฯ)
# จะไม่ถูกเขียนลง logs/bot.log และไม่ผ่าน LOG_LEVEL ที่ตั้งไว้ใน config เลย
# มีแค่ WARNING ขึ้นไปที่หลุดออก stderr ผ่าน Python's last-resort handler
# แบบ format ไม่ตรงกับที่ตั้งไว้เท่านั้น

from utils.logger import logger

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_MODEL            = "gemini-3.1-flash-lite"
DEFAULT_MAX_TOKENS       = 8192
DEFAULT_TEMPERATURE      = 1.0
DEFAULT_RETRY_ATTEMPTS   = 3
DEFAULT_RETRY_DELAY      = 1.0   # seconds (base delay, multiplied per attempt)

# MIME types recognised as inline blobs
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_TEXT_EXTS  = {".txt"}
_CSV_EXTS   = {".csv"}
_JSON_EXTS  = {".json"}
_DOCX_EXTS  = {".docx"}
_PDF_EXTS   = {".pdf"}

# ─── Custom Exceptions ────────────────────────────────────────────────────────

class GeminiError(Exception):
    """Base exception for all Gemini wrapper errors."""


class GeminiRetryExhausted(GeminiError):
    """Raised when all retry attempts are consumed."""


class GeminiFileError(GeminiError):
    """Raised when a file cannot be loaded or its type is unsupported."""


class GeminiResponseError(GeminiError):
    """Raised when the model response cannot be parsed."""


# ─── File Loaders ─────────────────────────────────────────────────────────────

def _read_text(path: str, label: str | None = None) -> str:
    """Read a plain-text file and optionally prepend a label."""
    content = Path(path).read_text(encoding="utf-8", errors="replace")
    if label:
        return f"[{label}]\n{content}"
    return content


def _read_bytes(path: str) -> tuple[bytes, str]:
    """Return raw bytes and guessed MIME type for a file."""
    raw  = Path(path).read_bytes()
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return raw, mime


def _read_docx(path: str) -> str:
    """Extract plain text from a DOCX file (requires python-docx)."""
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise GeminiFileError(
            "python-docx is not installed.  Run: pip install python-docx"
        ) from exc

    doc   = Document(path)
    lines = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(lines)


def _file_to_part(path: str) -> Union[types.Part, str]:
    """
    Convert any supported file path into either a Gemini ``types.Part``
    (for binary files) or a plain string (for text-like files).

    Supported extensions
    ─────────────────────
      Images : .jpg .jpeg .png .gif .webp .bmp  →  inline blob Part
      PDF    : .pdf                              →  inline blob Part
      DOCX   : .docx                             →  extracted text string
      TXT    : .txt                              →  raw text string
      CSV    : .csv                              →  raw text string
      JSON   : .json                             →  pretty-printed text string
    """
    ext = Path(path).suffix.lower()

    # ── Text files → plain string ──────────────────────────────────────────
    if ext in _TEXT_EXTS:
        return _read_text(path)

    if ext in _CSV_EXTS:
        return _read_text(path, label="CSV Data")

    if ext in _JSON_EXTS:
        raw_json = json.loads(Path(path).read_text(encoding="utf-8"))
        pretty   = json.dumps(raw_json, ensure_ascii=False, indent=2)
        return f"[JSON Data]\n{pretty}"

    if ext in _DOCX_EXTS:
        return f"[Document Content]\n{_read_docx(path)}"

    # ── Binary files → inline blob Part ───────────────────────────────────
    if ext in _PDF_EXTS:
        raw, _ = _read_bytes(path)
        return types.Part.from_bytes(data=raw, mime_type="application/pdf")

    if ext in _IMAGE_EXTS:
        raw, mime = _read_bytes(path)
        return types.Part.from_bytes(data=raw, mime_type=mime)

    # ── Fallback: try as UTF-8 text ────────────────────────────────────────
    try:
        return _read_text(path)
    except Exception as exc:
        raise GeminiFileError(f"Unsupported or unreadable file type: {ext!r}  ({path})") from exc


# ─── Retry Decorators ─────────────────────────────────────────────────────────

from google.genai import errors as _genai_errors

# HTTP status ที่ "retry แล้วมีโอกาสสำเร็จ" เท่านั้น
# 429 = quota/rate limit, 500/502/503/504 = server ฝั่ง Google มีปัญหาชั่วคราว
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    """
    ตัดสินว่า exception นี้ควร retry ไหม

    - google.genai.errors.APIError (และลูกคลาส ClientError/ServerError)
      มี .code เป็น HTTP status ใช้เช็คได้ตรงๆ
    - asyncio.TimeoutError / TimeoutError → retry ได้ (เน็ตหลุดชั่วคราว)
    - อย่างอื่นที่ไม่รู้จัก (เช่น 400 Bad Request, 401/403 API key ผิด,
      เนื้อหาโดน safety block) → ไม่ retry เพราะยิงซ้ำก็พังเหมือนเดิม
      เสียเวลา + เสียโควต้าฟรีเปล่าๆ
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True

    if isinstance(exc, _genai_errors.APIError):
        return getattr(exc, "code", None) in _RETRYABLE_STATUS

    # ไม่รู้จัก type นี้ — กันเหนียวไว้ก่อนว่า "ลองอีกครั้งได้" เพราะอาจเป็น
    # ปัญหาเครือข่ายที่ SDK ห่อ exception เป็นชนิดอื่น
    return True


def _sync_retry(func):
    """Wrap a sync method with exponential back-off retry (เฉพาะ error ที่ retry แล้วมีโอกาสสำเร็จ)."""
    def wrapper(self: "GeminiClient", *args, **kwargs):
        attempts = self.retry_attempts
        delay    = self.retry_delay
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return func(self, *args, **kwargs)
            except (GeminiError, GeminiRetryExhausted):
                raise   # don't retry logic errors — re-raise immediately
            except Exception as exc:
                last_exc = exc

                if not _is_retryable(exc):
                    logger.warning(
                        "[Gemini] Non-retryable error — %s: %s",
                        type(exc).__name__, exc,
                    )
                    raise GeminiError(f"Non-retryable error: {exc}") from exc

                logger.warning(
                    "[Gemini] Attempt %d/%d failed — %s: %s",
                    attempt, attempts, type(exc).__name__, exc,
                )
                if attempt < attempts:
                    sleep_for = delay * attempt
                    logger.debug("[Gemini] Retrying in %.1fs …", sleep_for)
                    time.sleep(sleep_for)

        raise GeminiRetryExhausted(
            f"All {attempts} attempts failed.  Last error: {last_exc}"
        ) from last_exc

    wrapper.__name__ = func.__name__
    wrapper.__doc__  = func.__doc__
    return wrapper


def _async_retry(func):
    """Wrap an async method with exponential back-off retry (เฉพาะ error ที่ retry แล้วมีโอกาสสำเร็จ)."""
    async def wrapper(self: "GeminiClient", *args, **kwargs):
        attempts = self.retry_attempts
        delay    = self.retry_delay
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await func(self, *args, **kwargs)
            except (GeminiError, GeminiRetryExhausted):
                raise
            except Exception as exc:
                last_exc = exc

                if not _is_retryable(exc):
                    logger.warning(
                        "[Gemini/async] Non-retryable error — %s: %s",
                        type(exc).__name__, exc,
                    )
                    raise GeminiError(f"Non-retryable error: {exc}") from exc

                logger.warning(
                    "[Gemini/async] Attempt %d/%d failed — %s: %s",
                    attempt, attempts, type(exc).__name__, exc,
                )
                if attempt < attempts:
                    sleep_for = delay * attempt
                    logger.debug("[Gemini/async] Retrying in %.1fs …", sleep_for)
                    await asyncio.sleep(sleep_for)

        raise GeminiRetryExhausted(
            f"All {attempts} async attempts failed.  Last error: {last_exc}"
        ) from last_exc

    wrapper.__name__ = func.__name__
    wrapper.__doc__  = func.__doc__
    return wrapper


# ─── GeminiClient ─────────────────────────────────────────────────────────────

class GeminiClient:
    """
    High-level Gemini AI client built on ``google-genai`` SDK 2.10.0.

    Parameters
    ──────────
    api_key           : Gemini API key
    model             : Model name (default: ``gemini-2.0-flash``)
    system_instruction: System prompt injected on every request
    temperature       : Sampling temperature 0.0–2.0 (default: 1.0)
    max_output_tokens : Maximum tokens in the response (default: 8192)
    retry_attempts    : How many times to retry on transient errors (default: 3)
    retry_delay       : Base delay in seconds between retries (default: 1.0)
    """

    def __init__(
        self,
        api_key: str,
        model: str                          = DEFAULT_MODEL,
        system_instruction: Optional[str]   = None,
        temperature: float                  = DEFAULT_TEMPERATURE,
        max_output_tokens: int              = DEFAULT_MAX_TOKENS,
        top_p: Optional[float]              = None,
        top_k: Optional[int]               = None,
        retry_attempts: int                 = DEFAULT_RETRY_ATTEMPTS,
        retry_delay: float                  = DEFAULT_RETRY_DELAY,
    ) -> None:
        self.client             = genai.Client(api_key=api_key)
        self.model              = model
        self.system_instruction = system_instruction
        self.temperature        = temperature
        self.max_output_tokens  = max_output_tokens
        self.top_p              = top_p
        self.top_k              = top_k
        self.retry_attempts     = retry_attempts
        self.retry_delay        = retry_delay

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_config(self, use_search: bool = False) -> types.GenerateContentConfig:
        """Build GenerateContentConfig with optional Google Search grounding."""
        tools: list[types.Tool] = []
        if use_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))

        return types.GenerateContentConfig(
            system_instruction = self.system_instruction,
            temperature        = self.temperature,
            max_output_tokens  = self.max_output_tokens,
            top_p              = self.top_p,
            top_k              = self.top_k,
            tools              = tools or None,
        )

    def _build_contents(
        self,
        prompt: str,
        files: Optional[list[str]] = None,
    ) -> list[Any]:
        """
        Assemble a ``contents`` list accepted by the Gemini API.

        Files are prepended (binary blobs or text strings) followed by the
        user's text prompt.  All items are wrapped in a single user turn.
        """
        parts: list[Any] = []

        if files:
            for filepath in files:
                try:
                    part = _file_to_part(filepath)
                    parts.append(part)
                    logger.debug("[Gemini] Loaded file: %s", filepath)
                except GeminiFileError:
                    raise
                except Exception as exc:
                    raise GeminiFileError(
                        f"Failed to load file '{filepath}': {exc}"
                    ) from exc

        parts.append(prompt)

        # Wrap in a single user-role message
        return [types.Content(role="user", parts=[
            p if isinstance(p, types.Part) else types.Part.from_text(text=p)
            for p in parts
        ])]

    def _extract_text(self, response: Any) -> str:
        """Safely extract `.text` from a Gemini response."""
        try:
            text = response.text
        except Exception as exc:
            raise GeminiResponseError(
                f"Could not extract text from model response: {exc}"
            ) from exc

        if text is None:
            raise GeminiResponseError(
                "Model returned an empty response (text is None). "
                "This may happen when content is blocked by safety filters."
            )
        return text

    def _dict_contents_to_sdk(self, contents: list[dict]) -> list[types.Content]:
        """
        แปลง contents แบบ Gemini REST format
        (เช่นที่ ai.context.build_contents() คืนมา) —
            [{"role": "user", "parts": [{"text": "..."}]}, ...]
        ให้เป็น list ของ ``types.Content`` ที่ SDK ``google-genai`` ใช้งานได้

        รองรับ part ที่มีคีย์ ``text`` เท่านั้น (พอสำหรับ history แบบข้อความ
        ของบอทนี้) — ถ้าต้องส่งไฟล์/รูปไปด้วย ให้ใช้พารามิเตอร์ ``files`` ของ
        ``generate`` / ``async_generate`` แทน ซึ่งจะถูกแนบเข้าไปในเทิร์น
        สุดท้ายให้อัตโนมัติ
        """
        sdk_contents: list[types.Content] = []

        for turn in contents:
            role = turn.get("role", "user")
            # Gemini SDK ใช้ role "model" สำหรับฝั่ง AI (ไม่ใช่ "assistant")
            if role not in ("user", "model"):
                role = "user"

            sdk_parts: list[types.Part] = []
            for part in turn.get("parts", []):
                text = part.get("text", "") if isinstance(part, dict) else str(part)
                if text:
                    sdk_parts.append(types.Part.from_text(text=text))

            if sdk_parts:
                sdk_contents.append(types.Content(role=role, parts=sdk_parts))

        return sdk_contents

    def _attach_files_to_contents(
        self,
        sdk_contents: list[types.Content],
        files: Optional[list[str]],
    ) -> list[types.Content]:
        """
        แนบไฟล์เข้าไปในเทิร์น user ล่าสุดของ sdk_contents อย่างปลอดภัย

        เดิมโค้ดใช้ ``sdk_contents[-1].parts.extend(file_parts)`` ซึ่ง
        สมมติว่า ``types.Content.parts`` เป็น mutable list เสมอ ถ้า SDK
        เวอร์ชันไหนคืน parts เป็น tuple หรือ pydantic model แบบ frozen
        บรรทัดนั้นจะพังด้วย AttributeError ทันทีที่มีคนแนบไฟล์มาพร้อม
        ประวัติแชท จึงเปลี่ยนมาสร้าง ``types.Content`` ตัวใหม่แทนการ
        mutate ของเดิม — ปลอดภัยไม่ว่า parts จะเป็น list หรือ tuple
        """
        if not files:
            return sdk_contents

        file_parts = [_file_to_part(fp) for fp in files]
        file_parts = [
            p if isinstance(p, types.Part) else types.Part.from_text(text=p)
            for p in file_parts
        ]

        if sdk_contents and sdk_contents[-1].role == "user":
            last = sdk_contents[-1]
            merged_parts = list(last.parts or []) + file_parts
            sdk_contents = sdk_contents[:-1] + [
                types.Content(role="user", parts=merged_parts)
            ]
        else:
            sdk_contents = sdk_contents + [
                types.Content(role="user", parts=file_parts)
            ]

        return sdk_contents

    # ── Sync/Async: Generate from pre-built contents (multi-turn) ─────────────

    @_sync_retry
    def generate_from_contents(
        self,
        contents: list[dict],
        files: Optional[list[str]] = None,
        use_search: bool           = False,
    ) -> str:
        """
        เหมือน :meth:`generate` แต่รับ ``contents`` แบบ multi-turn ที่ build
        มาแล้ว (list ของ {"role", "parts": [{"text": ...}]}) เช่นผลลัพธ์จาก
        ``ai.context.build_contents(...)`` แทนที่จะรับ prompt string เดียว

        ถ้ามี ``files`` จะถูกแนบเพิ่มเข้าไปในเทิร์นผู้ใช้ล่าสุด
        """
        sdk_contents = self._dict_contents_to_sdk(contents)
        sdk_contents = self._attach_files_to_contents(sdk_contents, files)

        config = self._build_config(use_search=use_search)

        response = self.client.models.generate_content(
            model    = self.model,
            contents = sdk_contents,
            config   = config,
        )
        return self._extract_text(response)

    @_async_retry
    async def async_generate_from_contents(
        self,
        contents: list[dict],
        files: Optional[list[str]] = None,
        use_search: bool           = False,
    ) -> str:
        """รุ่น async ของ :meth:`generate_from_contents`"""
        sdk_contents = self._dict_contents_to_sdk(contents)
        sdk_contents = self._attach_files_to_contents(sdk_contents, files)

        config = self._build_config(use_search=use_search)

        response = await self.client.aio.models.generate_content(
            model    = self.model,
            contents = sdk_contents,
            config   = config,
        )
        return self._extract_text(response)

    # ── Async: Stream from pre-built contents (multi-turn) ───────────────────

    async def async_stream_from_contents(
        self,
        contents: list[dict],
        files: Optional[list[str]] = None,
        use_search: bool           = False,
    ) -> AsyncGenerator[str, None]:
        """
        Stream ตอบกลับแบบ chunk จาก multi-turn contents
        (ใช้งานร่วมกับ ENABLE_STREAMING ใน main.py)
        """
        sdk_contents = self._dict_contents_to_sdk(contents)
        sdk_contents = self._attach_files_to_contents(sdk_contents, files)

        cfg = self._build_config(use_search=use_search)

        try:
            async for chunk in await self.client.aio.models.generate_content_stream(
                model    = self.model,
                contents = sdk_contents,
                config   = cfg,
            ):
                if chunk.text:
                    yield chunk.text
        except GeminiError:
            raise
        except Exception as exc:
            raise GeminiError(f"Async stream (contents) error: {exc}") from exc

    # ── Sync: Generate ────────────────────────────────────────────────────────

    @_sync_retry
    def generate(
        self,
        prompt: str,
        files: Optional[list[str]]  = None,
        use_search: bool            = False,
    ) -> str:
        """
        Generate a text response (blocking / synchronous).

        Parameters
        ──────────
        prompt     : Text prompt
        files      : Optional list of file paths to include as context
                     (image / pdf / docx / txt / csv / json)
        use_search : Enable Google Search grounding

        Returns
        ───────
        Generated text as a plain string.

        Raises
        ──────
        GeminiFileError      – unreadable / unsupported file
        GeminiResponseError  – model returned no text
        GeminiRetryExhausted – transient API error after all retries
        """
        contents = self._build_contents(prompt, files)
        config   = self._build_config(use_search=use_search)

        response = self.client.models.generate_content(
            model    = self.model,
            contents = contents,
            config   = config,
        )
        return self._extract_text(response)

    # ── Async: Generate ───────────────────────────────────────────────────────

    @_async_retry
    async def async_generate(
        self,
        prompt: str,
        files: Optional[list[str]]  = None,
        use_search: bool            = False,
    ) -> str:
        """
        Generate a text response (async / non-blocking).

        Parameters
        ──────────
        Same as :meth:`generate`.

        Example
        ───────
        ::

            result = await client.async_generate("Hello!")
        """
        contents = self._build_contents(prompt, files)
        config   = self._build_config(use_search=use_search)

        response = await self.client.aio.models.generate_content(
            model    = self.model,
            contents = contents,
            config   = config,
        )
        return self._extract_text(response)

    # ── Streaming: Sync ───────────────────────────────────────────────────────

    def stream(
        self,
        prompt: str,
        files: Optional[list[str]]  = None,
        use_search: bool            = False,
    ) -> Generator[str, None, None]:
        """
        Stream text chunks synchronously.

        Yields text chunks as they arrive from the model.

        Example
        ───────
        ::

            for chunk in client.stream("Tell me a long story"):
                print(chunk, end="", flush=True)
            print()   # final newline
        """
        contents = self._build_contents(prompt, files)
        config   = self._build_config(use_search=use_search)

        try:
            for chunk in self.client.models.generate_content_stream(
                model    = self.model,
                contents = contents,
                config   = config,
            ):
                if chunk.text:
                    yield chunk.text
        except GeminiError:
            raise
        except Exception as exc:
            raise GeminiError(f"Streaming error: {exc}") from exc

    # ── Streaming: Async ──────────────────────────────────────────────────────

    async def async_stream(
        self,
        prompt: str,
        files: Optional[list[str]]  = None,
        use_search: bool            = False,
    ) -> AsyncGenerator[str, None]:
        """
        Stream text chunks asynchronously.

        Yields text chunks as they arrive from the model.

        Example
        ───────
        ::

            async for chunk in client.async_stream("Tell me a story"):
                print(chunk, end="", flush=True)
            print()
        """
        contents = self._build_contents(prompt, files)
        config   = self._build_config(use_search=use_search)

        try:
            async for chunk in await self.client.aio.models.generate_content_stream(
                model    = self.model,
                contents = contents,
                config   = config,
            ):
                if chunk.text:
                    yield chunk.text
        except GeminiError:
            raise
        except Exception as exc:
            raise GeminiError(f"Async streaming error: {exc}") from exc

    # ── Convenience shortcuts ─────────────────────────────────────────────────

    def chat(self, prompt: str) -> str:
        """Simple text-only chat (sync)."""
        return self.generate(prompt)

    def with_image(self, prompt: str, image_path: str) -> str:
        """Send a text prompt together with an image."""
        return self.generate(prompt, files=[image_path])

    def with_pdf(self, prompt: str, pdf_path: str) -> str:
        """Send a text prompt together with a PDF document."""
        return self.generate(prompt, files=[pdf_path])

    def with_document(self, prompt: str, doc_path: str) -> str:
        """Send a text prompt together with any supported document."""
        return self.generate(prompt, files=[doc_path])

    def with_files(
        self,
        prompt: str,
        file_paths: list[str],
        use_search: bool = False,
    ) -> str:
        """Send a text prompt together with multiple files."""
        return self.generate(prompt, files=file_paths, use_search=use_search)

    def search(self, prompt: str) -> str:
        """Text prompt with Google Search grounding enabled."""
        return self.generate(prompt, use_search=True)

    # ── Async convenience shortcuts ───────────────────────────────────────────

    async def async_chat(self, prompt: str) -> str:
        """Simple text-only chat (async)."""
        return await self.async_generate(prompt)

    async def async_with_image(self, prompt: str, image_path: str) -> str:
        """Async text + image."""
        return await self.async_generate(prompt, files=[image_path])

    async def async_with_document(self, prompt: str, doc_path: str) -> str:
        """Async text + any supported document."""
        return await self.async_generate(prompt, files=[doc_path])

    async def async_search(self, prompt: str) -> str:
        """Async text + Google Search grounding."""
        return await self.async_generate(prompt, use_search=True)

    # ── Runtime info ─────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"GeminiClient("
            f"model={self.model!r}, "
            f"temperature={self.temperature}, "
            f"max_output_tokens={self.max_output_tokens}, "
            f"retry_attempts={self.retry_attempts}"
            f")"
        )


# ─── Module-level helper (optional) ──────────────────────────────────────────

def create_client(
    api_key: str,
    system_instruction: Optional[str] = None,
    model: str                        = DEFAULT_MODEL,
    **kwargs: Any,
) -> GeminiClient:
    """
    Factory helper — create a :class:`GeminiClient` with one call.

    Example
    ───────
    ::

        from ai.gemini import create_client

        client = create_client(
            api_key="YOUR_KEY",
            system_instruction="You are a concise assistant.",
        )
        print(client.chat("Hi!"))
    """
    return GeminiClient(
        api_key            = api_key,
        model              = model,
        system_instruction = system_instruction,
        **kwargs,
    )


# ─── Module-level singleton + `ask()` helper ─────────────────────────────────
#
# main.py ใช้แบบนี้:
#     from ai.gemini import ask
#     reply = await ask(contents)
#
# โดย `contents` คือ list แบบ Gemini REST format ที่ได้จาก
# ai.context.build_contents(history) เช่น:
#     [{"role": "user", "parts": [{"text": "สวัสดี"}]}, ...]
#
# ฟังก์ชันนี้สร้าง GeminiClient ตัวเดียว (singleton) จาก config.py ตัวจริง
# ของโปรเจกต์ (MODEL_NAME / TEMPERATURE / MAX_OUTPUT_TOKENS) แล้วดึง
# SYSTEM_PROMPT จาก ai/system_prompt.py มาใช้เป็น system_instruction

import config as _config

try:
    from ai.system_prompt import SYSTEM_PROMPT as _SYSTEM_PROMPT
except ImportError:
    _SYSTEM_PROMPT = None

_default_client: Optional["GeminiClient"] = None


def _get_default_client() -> "GeminiClient":
    """Lazily create (once) and cache the module-level GeminiClient."""
    global _default_client
    if _default_client is None:
        _default_client = GeminiClient(
            api_key             = _config.GEMINI_API_KEY,
            model               = getattr(_config, "MODEL_NAME",        DEFAULT_MODEL),
            system_instruction  = _SYSTEM_PROMPT,
            temperature         = getattr(_config, "TEMPERATURE",        DEFAULT_TEMPERATURE),
            max_output_tokens   = getattr(_config, "MAX_OUTPUT_TOKENS",  DEFAULT_MAX_TOKENS),
            top_p               = getattr(_config, "TOP_P",              None),
            top_k               = getattr(_config, "TOP_K",              None),
        )
    return _default_client


async def ask(
    contents: Union[str, list],
    *,
    files: Optional[list[str]] = None,
    use_search: Optional[bool] = None,
) -> str:
    """
    Convenience entry point used by main.py.

    Parameters
    ──────────
    contents   : ผลลัพธ์จาก ai.context.build_contents(history) —
                 list ของ {"role": "user"/"model", "parts": [{"text": ...}]}
                 (หรือจะส่ง string เดี่ยวๆ ก็ได้ เผื่อใช้ที่อื่น)
    files      : ไฟล์แนบเพิ่มเติม (ถ้ามี)
    use_search : เปิด Google Search grounding (ถ้าไม่ระบุ จะใช้ค่าจาก
                 config.ENABLE_GOOGLE_SEARCH)

    Returns
    ───────
    คำตอบจากโมเดลเป็น plain string
    """
    if use_search is None:
        use_search = getattr(_config, "ENABLE_GOOGLE_SEARCH", False)

    client = _get_default_client()

    if isinstance(contents, str):
        return await client.async_generate(contents, files=files, use_search=use_search)

    # list แบบ Gemini REST format จาก build_contents()
    return await client.async_generate_from_contents(
        contents, files=files, use_search=use_search
    )


async def ask_stream(
    contents: Union[str, list],
    *,
    files: Optional[list[str]] = None,
    use_search: Optional[bool] = None,
) -> AsyncGenerator[str, None]:
    """
    เหมือน ask() แต่ yield ทีละ chunk (ใช้กับ ENABLE_STREAMING)

    Usage ใน main.py
    ────────────────
        async for chunk in ask_stream(contents):
            buffer += chunk
    """
    if use_search is None:
        use_search = getattr(_config, "ENABLE_GOOGLE_SEARCH", False)

    client = _get_default_client()

    if isinstance(contents, str):
        async for chunk in client.async_stream(contents, files=files, use_search=use_search):
            yield chunk
    else:
        async for chunk in client.async_stream_from_contents(contents, files=files, use_search=use_search):
            yield chunk


# ─── Quick self-test (python -m ai.gemini) ────────────────────────────────────

if __name__ == "__main__":
    import os
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set the GEMINI_API_KEY environment variable first.")
        sys.exit(1)

    client = create_client(
        api_key            = api_key,
        system_instruction = "You are a friendly assistant. Keep answers short.",
    )

    print("─── Text ─────────────────────────────────────────────")
    print(client.chat("Say hello in Thai in one sentence."))

    print("\n─── Streaming ────────────────────────────────────────")
    for chunk in client.stream("Count from 1 to 5 slowly."):
        print(chunk, end="", flush=True)
    print()

    print("\n─── Google Search ────────────────────────────────────")
    print(client.search("What is today's date and day of the week?"))

    print("\n─── Async ────────────────────────────────────────────")
    async def _demo_async():
        result = await client.async_chat("What is 2 + 2? Answer with just the number.")
        print(result)

        print("\n─── Async Stream ─────────────────────────────────────")
        async for chunk in client.async_stream("List 3 colors, one per line."):
            print(chunk, end="", flush=True)
        print()

    asyncio.run(_demo_async())
    print("\n✅  All tests passed.")