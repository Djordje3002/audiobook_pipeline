"""Project constants, environment variables, paths, and ACX targets."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_AUDIO_DIR = BASE_DIR / "input_audio"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_AUDIO_DIR = BASE_DIR / "output_audio"
TEMP_CHUNKS_DIR = BASE_DIR / "temp_chunks"

ACX_RMS_MIN_DB = -23.0
ACX_RMS_MAX_DB = -18.0
ACX_RMS_TARGET_DB = -19.0
ACX_PEAK_MAX_DBFS = -3.0
ACX_PEAK_WORKING_CEILING_DBFS = -3.5
ACX_NOISE_FLOOR_MAX_DBFS = -60.0

PREVIEW_DURATION_SECONDS = 300
WHISPER_CHUNK_OVERLAP_SECONDS = 2
