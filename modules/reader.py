"""Local text reader for translated audiobook segments."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import requests
from pydub import AudioSegment

from config import OUTPUT_AUDIO_DIR
from config import ELEVENLABS_API_KEY, ELEVENLABS_MODEL_ID, ELEVENLABS_VOICE_ID


def _safe_book_title(raw_title: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in raw_title).strip("_") or "book"


def _derive_book_title_from_translated_path(translated_path: Path) -> str:
    stem = translated_path.stem
    if stem.endswith("_translated"):
        stem = stem[: -len("_translated")]
    return _safe_book_title(stem)


def _load_translated_segments(translated_path: Path) -> list[dict]:
    with open(translated_path, "r", encoding="utf-8") as input_file:
        segments = json.load(input_file)
    if not isinstance(segments, list):
        raise RuntimeError("Translated artifact is not a list of segments.")
    return segments


def _build_readback_text(segments: list[dict]) -> str:
    parts: list[str] = []
    for segment in segments:
        text = str(segment.get("translated_text", "")).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def _split_text_for_elevenlabs(text: str, max_chars: int = 2200) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= max_chars:
            current = paragraph
            continue

        # Hard-wrap very long paragraphs.
        start_idx = 0
        while start_idx < len(paragraph):
            end_idx = min(start_idx + max_chars, len(paragraph))
            chunks.append(paragraph[start_idx:end_idx].strip())
            start_idx = end_idx
        current = ""

    if current:
        chunks.append(current)
    return chunks


def _generate_output_path(book_title: str, suffix: str, extension: str) -> Path:
    readback_dir = Path(OUTPUT_AUDIO_DIR) / "readbacks"
    readback_dir.mkdir(parents=True, exist_ok=True)
    return readback_dir / f"{book_title}_{suffix}_{int(time.time())}.{extension}"


def _parse_elevenlabs_error(response: requests.Response) -> tuple[str, str]:
    status_code = response.status_code
    raw_text = (response.text or "")[:280]
    api_status = ""
    api_message = ""
    try:
        payload = response.json() or {}
        detail = payload.get("detail", {})
        if isinstance(detail, dict):
            api_status = str(detail.get("status", "")).strip()
            api_message = str(detail.get("message", "")).strip()
        elif isinstance(detail, str):
            api_message = detail.strip()
    except Exception:  # pylint: disable=broad-except
        pass

    if api_status == "quota_exceeded" or "quota" in api_message.lower():
        return (
            "ElevenLabs quota exceeded",
            f"{api_message or raw_text}. Add credits/upgrade or switch to local reader.",
        )
    if api_status in {"invalid_api_key", "unauthorized"} or status_code == 401:
        return (
            "ElevenLabs authentication failed",
            "Invalid ElevenLabs API key. Paste a valid key in the ElevenLabs card.",
        )
    if "voice" in api_message.lower() or api_status == "voice_not_found":
        return (
            "ElevenLabs voice error",
            f"{api_message or 'Voice ID not found.'} Select a free/premade voice from list or paste a valid Voice ID.",
        )
    if "model" in api_message.lower() or api_status == "model_not_found":
        return (
            "ElevenLabs model error",
            f"{api_message or 'Model not available for your plan.'} Try another model in the ElevenLabs card.",
        )
    if status_code == 429:
        return (
            "ElevenLabs rate limit",
            "Too many requests. Wait and retry, or generate shorter text.",
        )
    return (
        f"ElevenLabs request failed ({status_code})",
        api_message or raw_text or "Unknown ElevenLabs error.",
    )


def synthesize_translation_readback(
    translated_path: Path,
    explicit_book_title: str | None = None,
    speech_rate: int | None = None,
) -> Path:
    """Generate WAV narration from translated segments using local pyttsx3."""
    try:
        import pyttsx3  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError("pyttsx3 is not installed. Run `pip install pyttsx3`.") from exc

    segments = _load_translated_segments(translated_path)
    text = _build_readback_text(segments)
    if not text:
        raise RuntimeError("No translated text found. Run translation first.")

    book_title = _safe_book_title(explicit_book_title or _derive_book_title_from_translated_path(translated_path))
    output_path = _generate_output_path(book_title=book_title, suffix="readback_local", extension="wav")

    engine = pyttsx3.init()
    if isinstance(speech_rate, int) and speech_rate > 0:
        engine.setProperty("rate", speech_rate)

    engine.save_to_file(text, str(output_path))
    engine.runAndWait()

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Reader audio generation failed. No output file was produced.")

    return output_path


def synthesize_translation_readback_elevenlabs(
    translated_path: Path,
    explicit_book_title: str | None = None,
    api_key: str | None = None,
    voice_id: str | None = None,
    model_id: str | None = None,
    output_format: str = "mp3_44100_128",
) -> Path:
    """Generate MP3 narration from translated segments using ElevenLabs TTS API."""
    segments = _load_translated_segments(translated_path)
    text = _build_readback_text(segments)
    if not text:
        raise RuntimeError("No translated text found. Run translation first.")

    resolved_api_key = (api_key or ELEVENLABS_API_KEY or "").strip()
    resolved_voice_id = (voice_id or ELEVENLABS_VOICE_ID or "").strip()
    resolved_model_id = (model_id or ELEVENLABS_MODEL_ID or "eleven_multilingual_v2").strip()
    if not resolved_api_key:
        raise RuntimeError("Missing ElevenLabs API key. Provide it in UI or set ELEVENLABS_API_KEY in .env.")
    if not resolved_voice_id:
        raise RuntimeError("Missing ElevenLabs voice ID. Provide it in UI or set ELEVENLABS_VOICE_ID in .env.")

    book_title = _safe_book_title(explicit_book_title or _derive_book_title_from_translated_path(translated_path))
    output_path = _generate_output_path(book_title=book_title, suffix="readback_elevenlabs", extension="mp3")

    chunks = _split_text_for_elevenlabs(text)
    if not chunks:
        raise RuntimeError("Nothing to synthesize after chunking translated text.")

    combined_audio: AudioSegment | None = None
    silence = AudioSegment.silent(duration=120)
    for idx, chunk_text in enumerate(chunks, start=1):
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{resolved_voice_id}/stream"
        payload = {
            "text": chunk_text,
            "model_id": resolved_model_id,
            "output_format": output_format,
        }
        headers = {
            "xi-api-key": resolved_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        response = requests.post(url, json=payload, headers=headers, timeout=120)
        if response.status_code != 200:
            title, details = _parse_elevenlabs_error(response)
            raise RuntimeError(f"{title} on chunk {idx}/{len(chunks)}: {details}")

        piece = AudioSegment.from_file(io.BytesIO(response.content), format="mp3")
        if combined_audio is None:
            combined_audio = piece
        else:
            combined_audio = combined_audio + silence + piece

    if combined_audio is None:
        raise RuntimeError("ElevenLabs returned no audio output.")

    combined_audio.export(output_path, format="mp3", bitrate="128k")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("ElevenLabs readback export failed. No output file was produced.")
    return output_path
