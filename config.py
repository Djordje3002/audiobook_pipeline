"""Project-wide constants, environment variables, and quality targets."""

from __future__ import annotations

import os
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()

# API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# Models
OPENAI_MODEL = "gpt-4o"
WHISPER_MODEL = "whisper-1"
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"

# Book metadata (adjust per project)
BOOK_GENRE = "hardboiled thriller"
AUTHOR_STYLE = "Kamberi/Mijovic"

# Voice parameters
VOICE_STABILITY = 0.45
VOICE_SIMILARITY_BOOST = 0.82
VOICE_STYLE = 0.35
VOICE_SPEAKER_BOOST = True
AUDIO_FORMAT = "mp3_44100_192"

# Segmentation
MAX_CHARS_PER_SEGMENT = 1500
MIN_CHARS_PER_SEGMENT = 100
WHISPER_OVERLAP_SEC = 30
WHISPER_MAX_BYTES = 24 * 1024 * 1024  # 24 MB

# Audio processing
SAMPLE_RATE = 44100
CHANNELS = 1
CROSSFADE_MS = 80
SILENCE_BETWEEN_SEG_MS = 200
SILENCE_CHAPTER_END_MS = 1500
EXPORT_MP3_BITRATE = "192k"

# ACX standards
ACX_RMS_MIN_DB = -23.0
ACX_RMS_MAX_DB = -18.0
ACX_RMS_TARGET_DB = -19.0
ACX_PEAK_MAX_DB = -3.0
ACX_PEAK_TARGET_DB = -3.5
ACX_NOISE_FLOOR_DB = -60.0
NOISE_GATE_DB = -50.0

# Rate limiting / retries
REQUEST_DELAY_SEC = 1.1
ELEVENLABS_RETRY_COUNT = 3
OPENAI_RETRY_COUNT = 3

# Paths
INPUT_AUDIO_DIR = "input_audio/"
OUTPUT_AUDIO_DIR = "output_audio/"
OUTPUT_FINAL_DIR = "output_audio/final/"
OUTPUT_PREVIEW_DIR = "output_audio/previews/"
OUTPUT_TRANSLATED_DIR = "output/translated/"
OUTPUT_REPORTS_DIR = "output/reports/"
TEMP_CHUNKS_DIR = "temp_chunks/"

# Preview
PREVIEW_MINUTES = 5

# Translation validation thresholds (warnings only)
TRANSLATION_MIN_RATIO = 0.5
TRANSLATION_MAX_RATIO = 2.0

REQUIRED_ENV_VARS = (
    "OPENAI_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
)


def missing_required_env_vars() -> list[str]:
    """Return required env var names that are missing or empty."""
    missing = []
    for var_name in REQUIRED_ENV_VARS:
        value = os.getenv(var_name, "").strip()
        if not value:
            missing.append(var_name)
    return missing


def ensure_required_env_vars(extra_vars: Iterable[str] = ()) -> None:
    """Raise a clear error if required environment variables are missing."""
    all_required = list(REQUIRED_ENV_VARS) + list(extra_vars)
    missing = [name for name in all_required if not os.getenv(name, "").strip()]
    if missing:
        missing_display = ", ".join(sorted(set(missing)))
        raise RuntimeError(
            "Missing required environment variables: "
            f"{missing_display}. Set them in .env before running the pipeline."
        )
