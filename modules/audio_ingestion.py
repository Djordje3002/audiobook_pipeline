"""Whisper transcription, chunking, overlap handling, and segment grouping."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from openai import OpenAI
from pydub import AudioSegment

from config import (
    MAX_CHARS_PER_SEGMENT,
    OUTPUT_TRANSLATED_DIR,
    OPENAI_API_KEY,
    TEMP_CHUNKS_DIR,
    WHISPER_MAX_BYTES,
    WHISPER_MODEL,
    WHISPER_OVERLAP_SEC,
)


def _get_client() -> OpenAI:
    return OpenAI(api_key=OPENAI_API_KEY)


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

    temp_dir = Path(TEMP_CHUNKS_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)

    for stale in sorted(temp_dir.glob("chunk_*.mp3")):
        stale.unlink(missing_ok=True)

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
            }
        )

    return chunks


def transcribe_audio(filepath: str) -> list[dict]:
    """Transcribe Serbian audio and return normalized timestamped segments."""
    client = _get_client()
    chunks = split_audio_for_whisper(filepath)
    all_segments: list[dict] = []

    for chunk in chunks:
        chunk_path = chunk["path"]
        print(f"  Transcribing chunk: {os.path.basename(chunk_path)}")
        with open(chunk_path, "rb") as chunk_file:
            response = client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=chunk_file,
                language="sr",
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

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
