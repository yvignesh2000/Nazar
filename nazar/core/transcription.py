"""
InnerVoice — Audio Transcription

Transcribes WhatsApp voice notes using Groq's Whisper API.
Groq free tier: 7,200 minutes/day — more than enough for any realistic load.

WhatsApp sends voice notes as audio/ogg (opus codec).
Groq Whisper accepts this natively — no ffmpeg conversion needed.
"""

import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger("innervoice")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-large-v3-turbo"

# Map InnerVoice language codes to Whisper language codes
LANGUAGE_MAP = {
    "hi": "hi",   # Hindi
    "ta": "ta",   # Tamil
    "te": "te",   # Telugu
    "kn": "kn",   # Kannada
    "mr": "mr",   # Marathi
    "bn": "bn",   # Bengali
    "gu": "gu",   # Gujarati
    "ml": "ml",   # Malayalam
    "en": "en",   # English
}


class TranscriptionError(Exception):
    pass


async def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    language_hint: Optional[str] = None,
) -> str:
    """
    Transcribe audio bytes using Groq Whisper API.

    Args:
        audio_bytes: Raw audio data (WhatsApp sends audio/ogg; codecs=opus)
        mime_type: MIME type of the audio
        language_hint: ISO language code hint (e.g. "hi", "ta") from user profile

    Returns:
        Transcript as plain text string

    Raises:
        TranscriptionError: If transcription fails or API is unavailable
    """
    if not GROQ_API_KEY:
        raise TranscriptionError("GROQ_API_KEY not set")

    if not audio_bytes:
        raise TranscriptionError("Empty audio data")

    # Determine file extension from mime type
    ext = "ogg"
    if "mp4" in mime_type or "mpeg" in mime_type:
        ext = "mp3"
    elif "webm" in mime_type:
        ext = "webm"

    # Resolve language hint
    whisper_lang = LANGUAGE_MAP.get(language_hint) if language_hint else None

    try:
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                audio_bytes,
                filename=f"audio.{ext}",
                content_type=mime_type,
            )
            form.add_field("model", WHISPER_MODEL)
            form.add_field("response_format", "text")
            if whisper_lang:
                form.add_field("language", whisper_lang)

            async with session.post(
                GROQ_TRANSCRIPTION_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                data=form,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    transcript = await resp.text()
                    transcript = transcript.strip()
                    if not transcript:
                        raise TranscriptionError("Empty transcript returned")
                    return transcript
                else:
                    error = await resp.text()
                    logger.error(f"Groq Whisper API error ({resp.status}): {error}")
                    raise TranscriptionError(f"Groq API returned {resp.status}")

    except TranscriptionError:
        raise
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        raise TranscriptionError(str(e))
