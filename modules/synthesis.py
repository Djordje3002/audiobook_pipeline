"""ElevenLabs Speech-to-Speech synthesis with TTS fallback and resume support."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from tqdm import tqdm

from config import (
    AUDIO_FORMAT,
    ELEVENLABS_API_KEY,
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_RETRY_COUNT,
    ELEVENLABS_VOICE_ID,
    OUTPUT_AUDIO_DIR,
    REQUEST_DELAY_SEC,
    VOICE_SIMILARITY_BOOST,
    VOICE_SPEAKER_BOOST,
    VOICE_STABILITY,
    VOICE_STYLE,
)
from modules.audio_ingestion import extract_audio_segment


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def call_s2s_api(audio_filepath: str, retry_count: int = ELEVENLABS_RETRY_COUNT) -> bytes | None:
    """Call ElevenLabs Speech-to-Speech endpoint and return MP3 bytes."""
    url = f"https://api.elevenlabs.io/v1/speech-to-speech/{ELEVENLABS_VOICE_ID}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg",
    }
    voice_settings = json.dumps(
        {
            "stability": VOICE_STABILITY,
            "similarity_boost": VOICE_SIMILARITY_BOOST,
            "style": VOICE_STYLE,
            "use_speaker_boost": VOICE_SPEAKER_BOOST,
        }
    )

    for attempt in range(retry_count):
        try:
            with open(audio_filepath, "rb") as audio_file:
                response = requests.post(
                    url,
                    headers=headers,
                    files={"audio": (os.path.basename(audio_filepath), audio_file, "audio/mpeg")},
                    data={
                        "model_id": ELEVENLABS_MODEL_ID,
                        "voice_settings": voice_settings,
                        "output_format": AUDIO_FORMAT,
                    },
                    timeout=120,
                )
            if response.status_code == 200:
                return response.content
            if response.status_code == 429:
                print("  ElevenLabs rate limit hit. Waiting 60s before retry.")
                time.sleep(60)
            else:
                print(f"  S2S API error {response.status_code}: {response.text[:180]}")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  S2S request error: {exc}")

        if attempt < retry_count - 1:
            time.sleep(2 ** (attempt + 1))
    return None


def call_tts_api(text: str, retry_count: int = ELEVENLABS_RETRY_COUNT) -> bytes | None:
    """Fallback ElevenLabs text-to-speech."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": VOICE_STABILITY,
            "similarity_boost": VOICE_SIMILARITY_BOOST,
            "style": VOICE_STYLE,
            "use_speaker_boost": VOICE_SPEAKER_BOOST,
        },
        "output_format": AUDIO_FORMAT,
    }

    for attempt in range(retry_count):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            if response.status_code == 200:
                return response.content
            if response.status_code == 429:
                print("  ElevenLabs TTS rate limit hit. Waiting 60s before retry.")
                time.sleep(60)
            else:
                print(f"  TTS API error {response.status_code}: {response.text[:180]}")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  TTS request error: {exc}")

        if attempt < retry_count - 1:
            time.sleep(2 ** (attempt + 1))
    return None


def save_audio_segment(audio_bytes: bytes, chapter_num: int, segment_index: int) -> str:
    """Persist synthesized segment audio and return file path."""
    chapter_dir = Path(OUTPUT_AUDIO_DIR) / f"chapter_{chapter_num:02d}"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    output_path = chapter_dir / f"seg_{segment_index:03d}.mp3"
    with open(output_path, "wb") as output_file:
        output_file.write(audio_bytes)
    return str(output_path)


def _load_manifest(manifest_path: Path) -> dict[int, dict]:
    if not manifest_path.exists():
        return {}
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        data = json.load(manifest_file)
    by_index: dict[int, dict] = {}
    for item in data:
        by_index[int(item["segment_index"])] = item
    return by_index


def _write_manifest(manifest_path: Path, by_index: dict[int, dict]) -> list[dict]:
    ordered = [by_index[idx] for idx in sorted(by_index)]
    with open(manifest_path, "w", encoding="utf-8") as manifest_file:
        json.dump(ordered, manifest_file, ensure_ascii=False, indent=2)
    return ordered


def synthesize_all_segments(segments: list[dict], original_audio_path: str, book_title: str) -> list[dict]:
    """Run S2S synthesis for all translated segments with resume and TTS fallback."""
    output_root = Path(OUTPUT_AUDIO_DIR)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / f"{book_title}_manifest.json"

    by_index = _load_manifest(manifest_path)
    done_indices = {
        idx
        for idx, item in by_index.items()
        if item.get("synthesis_status") == "success"
        and item.get("audio_path")
        and Path(str(item["audio_path"])).exists()
    }
    if done_indices:
        print(f"  Resume detected: {len(done_indices)} segments already synthesized")

    print(f"[SYNTHESIS] Processing {len(segments)} segments")
    for segment in tqdm(segments, desc="  S2S", unit="segment"):
        segment_index = int(segment["segment_index"])
        if segment_index in done_indices:
            continue

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
            temp_path = temp_file.name

        method = "s2s"
        error_message = None
        try:
            extract_audio_segment(
                source_path=original_audio_path,
                start_sec=float(segment["start"]),
                end_sec=float(segment["end"]),
                output_path=temp_path,
            )

            audio_bytes = call_s2s_api(temp_path)

            if not audio_bytes:
                translated_text = str(segment.get("translated_text", "")).strip()
                if translated_text:
                    print(f"  S2S failed for segment {segment_index}; trying TTS fallback")
                    audio_bytes = call_tts_api(translated_text)
                    method = "tts_fallback"
                else:
                    error_message = "Missing translated text for TTS fallback."

            if audio_bytes:
                audio_path = save_audio_segment(
                    audio_bytes=audio_bytes,
                    chapter_num=int(segment.get("chapter_num", 1)),
                    segment_index=segment_index,
                )
                manifest_entry = {
                    **segment,
                    "audio_path": audio_path,
                    "synthesis_status": "success",
                    "method": method,
                    "error": None,
                    "updated_at": _utc_now_iso(),
                }
            else:
                manifest_entry = {
                    **segment,
                    "audio_path": None,
                    "synthesis_status": "failed",
                    "method": method,
                    "error": error_message or "S2S and TTS both failed.",
                    "updated_at": _utc_now_iso(),
                }
        except Exception as exc:  # pylint: disable=broad-except
            manifest_entry = {
                **segment,
                "audio_path": None,
                "synthesis_status": "failed",
                "method": method,
                "error": f"Unexpected synthesis error: {exc}",
                "updated_at": _utc_now_iso(),
            }
        finally:
            Path(temp_path).unlink(missing_ok=True)

        by_index[segment_index] = manifest_entry
        _write_manifest(manifest_path, by_index)
        time.sleep(REQUEST_DELAY_SEC)

    final_manifest = _write_manifest(manifest_path, by_index)
    s2s_count = sum(1 for item in final_manifest if item.get("method") == "s2s")
    tts_count = sum(1 for item in final_manifest if item.get("method") == "tts_fallback")
    failed_count = sum(1 for item in final_manifest if item.get("synthesis_status") != "success")
    print(f"  S2S success: {s2s_count} | TTS fallback: {tts_count} | Failed: {failed_count}")
    return final_manifest
