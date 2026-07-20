"""Whisper transcription, chunking, overlap handling, and segment grouping."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import ffmpeg
from openai import OpenAI
from pydub import AudioSegment

from config import (
    MAX_CHARS_PER_SEGMENT,
    OUTPUT_TRANSLATED_DIR,
    TEMP_CHUNKS_DIR,
    WHISPER_MAX_BYTES,
    WHISPER_MODEL,
    WHISPER_OVERLAP_SEC,
    OPENAI_API_KEY,
)
from modules.languages import normalize_language_code


def _resolve_openai_api_key(api_key: str | None = None) -> str:
    resolved = str(api_key or OPENAI_API_KEY or "").strip()
    if not resolved:
        raise RuntimeError(
            "Missing OpenAI API key. Paste your key in the web app, "
            "or set OPENAI_API_KEY in .env for CLI usage."
        )
    return resolved


def _get_client(api_key: str | None = None) -> OpenAI:
    return OpenAI(api_key=_resolve_openai_api_key(api_key))


def _segment_field(segment: dict | object, key: str, default=None):
    """Read a segment field from dict-style or object-style segment values."""
    if isinstance(segment, dict):
        return segment.get(key, default)
    return getattr(segment, key, default)


def _response_segments(response) -> list:
    """Normalize Whisper response segment extraction across SDK response shapes."""
    if isinstance(response, dict):
        return response.get("segments", []) or []

    segments = getattr(response, "segments", None)
    if segments is not None:
        return segments

    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped.get("segments", []) or []

    return []


def probe_media_duration(filepath: str | Path) -> float:
    """Read media duration with ffprobe without decoding the full source file."""
    metadata = ffmpeg.probe(str(filepath))
    duration = float((metadata.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("Could not determine source duration.")
    return round(duration, 3)


def split_audio_for_whisper(filepath: str) -> list[dict]:
    """Split large audio into deterministic chunks that fit Whisper limits."""
    source_path = Path(filepath)
    if not source_path.exists():
        raise FileNotFoundError(f"Input audio not found: {source_path}")

    file_size = source_path.stat().st_size
    audio = AudioSegment.from_file(str(source_path))

    if file_size <= WHISPER_MAX_BYTES:
        return [
            {
                "path": str(source_path),
                "chunk_start_sec": 0.0,
                "core_start_sec": 0.0,
                "core_end_sec": len(audio) / 1000.0,
            }
        ]

    temp_root = Path(TEMP_CHUNKS_DIR)
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="whisper-", dir=temp_root))

    num_chunks = math.ceil(file_size / WHISPER_MAX_BYTES)
    chunk_duration_ms = math.ceil(len(audio) / num_chunks)
    overlap_ms = int(WHISPER_OVERLAP_SEC * 1000)

    chunks: list[dict] = []
    print(f"  Large audio detected ({file_size / 1024 / 1024:.1f} MB) -> {num_chunks} chunks")

    for index in range(num_chunks):
        core_start_ms = index * chunk_duration_ms
        core_end_ms = min((index + 1) * chunk_duration_ms, len(audio))
        export_start_ms = max(0, core_start_ms - overlap_ms)
        export_end_ms = min(len(audio), core_end_ms + overlap_ms)

        chunk_audio = audio[export_start_ms:export_end_ms]
        chunk_path = temp_dir / f"chunk_{index:03d}.mp3"
        chunk_audio.export(chunk_path, format="mp3", bitrate="128k")

        chunks.append(
            {
                "path": str(chunk_path),
                "chunk_start_sec": export_start_ms / 1000.0,
                "core_start_sec": core_start_ms / 1000.0,
                "core_end_sec": core_end_ms / 1000.0,
                "temporary": True,
            }
        )

    return chunks


def transcribe_audio(
    filepath: str,
    api_key: str | None = None,
    source_language: str = "auto",
) -> list[dict]:
    """Transcribe audio and return normalized timestamped segments."""
    client = _get_client(api_key=api_key)
    language_code = normalize_language_code(source_language, allow_auto=True)
    chunks = split_audio_for_whisper(filepath)
    all_segments: list[dict] = []

    temporary_directories = {
        Path(chunk["path"]).parent for chunk in chunks if chunk.get("temporary")
    }
    try:
        for chunk in chunks:
            chunk_path = chunk["path"]
            print(f"  Transcribing chunk: {os.path.basename(chunk_path)}")
            with open(chunk_path, "rb") as chunk_file:
                request_options = {
                    "model": WHISPER_MODEL,
                    "file": chunk_file,
                    "response_format": "verbose_json",
                    "timestamp_granularities": ["segment"],
                }
                if language_code != "auto":
                    request_options["language"] = language_code
                response = client.audio.transcriptions.create(**request_options)

            response_segments = _response_segments(response)
            chunk_offset = float(chunk["chunk_start_sec"])
            core_start = float(chunk["core_start_sec"])
            core_end = float(chunk["core_end_sec"])

            for segment in response_segments:
                start_value = _segment_field(segment, "start")
                end_value = _segment_field(segment, "end")
                text_value = _segment_field(segment, "text", "")

                if start_value is None or end_value is None:
                    continue

                absolute_start = float(start_value) + chunk_offset
                absolute_end = float(end_value) + chunk_offset
                midpoint = (absolute_start + absolute_end) / 2.0
                text = str(text_value).strip()
                if not text:
                    continue

                # Keep only the core range from each chunk to avoid overlap duplicates.
                if midpoint < core_start or midpoint > core_end:
                    continue

                all_segments.append(
                    {
                        "start": round(absolute_start, 3),
                        "end": round(absolute_end, 3),
                        "text": text,
                    }
                )
    finally:
        for directory in temporary_directories:
            shutil.rmtree(directory, ignore_errors=True)

    all_segments.sort(key=lambda item: (item["start"], item["end"]))
    print(f"  Total transcript segments: {len(all_segments)}")
    return all_segments


def extract_audio_segment(source_path: str, start_sec: float, end_sec: float, output_path: str) -> str:
    """Extract a single source-audio segment with tiny padding for natural cuts."""
    if end_sec <= start_sec:
        raise ValueError(f"Invalid segment bounds: start={start_sec}, end={end_sec}")

    audio = AudioSegment.from_file(source_path)
    padding_ms = 50
    start_ms = max(0, int(start_sec * 1000) - padding_ms)
    end_ms = min(len(audio), int(end_sec * 1000) + padding_ms)
    segment_audio = audio[start_ms:end_ms]
    segment_audio.export(output_path, format="mp3", bitrate="192k")
    return output_path


def group_segments(segments: list[dict], max_chars: int = MAX_CHARS_PER_SEGMENT) -> list[dict]:
    """Group short Whisper segments into synthesis-ready blocks."""
    grouped: list[dict] = []
    current_start: float | None = None
    current_end: float | None = None
    current_text_parts: list[str] = []

    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        if current_start is None:
            current_start = float(segment["start"])

        candidate_text = " ".join(current_text_parts + [text]).strip()
        if current_text_parts and len(candidate_text) > max_chars:
            grouped.append(
                {
                    "segment_index": len(grouped),
                    "chapter_num": 1,
                    "start": round(current_start, 3),
                    "end": round(float(current_end), 3),
                    "original_text": " ".join(current_text_parts).strip(),
                }
            )
            current_start = float(segment["start"])
            current_text_parts = [text]
        else:
            current_text_parts.append(text)

        current_end = float(segment["end"])

    if current_text_parts and current_start is not None and current_end is not None:
        grouped.append(
            {
                "segment_index": len(grouped),
                "chapter_num": 1,
                "start": round(current_start, 3),
                "end": round(current_end, 3),
                "original_text": " ".join(current_text_parts).strip(),
            }
        )

    print(f"  Grouped into {len(grouped)} synthesis segments")
    return grouped


def save_transcript(segments: list[dict], book_title: str) -> str:
    """Persist grouped transcript to JSON and return the file path."""
    os.makedirs(OUTPUT_TRANSLATED_DIR, exist_ok=True)
    transcript_path = Path(OUTPUT_TRANSLATED_DIR) / f"{book_title}_transcript.json"
    with open(transcript_path, "w", encoding="utf-8") as output_file:
        json.dump(segments, output_file, ensure_ascii=False, indent=2)
    print(f"  Saved transcript: {transcript_path}")
    return str(transcript_path)
