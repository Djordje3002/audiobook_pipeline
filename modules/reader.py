"""Local text reader for translated audiobook segments."""

from __future__ import annotations

import json
import time
from pathlib import Path

from config import OUTPUT_AUDIO_DIR


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
    readback_dir = Path(OUTPUT_AUDIO_DIR) / "readbacks"
    readback_dir.mkdir(parents=True, exist_ok=True)

    output_path = readback_dir / f"{book_title}_readback_{int(time.time())}.wav"

    engine = pyttsx3.init()
    if isinstance(speech_rate, int) and speech_rate > 0:
        engine.setProperty("rate", speech_rate)

    engine.save_to_file(text, str(output_path))
    engine.runAndWait()

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Reader audio generation failed. No output file was produced.")

    return output_path
