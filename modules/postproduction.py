"""FFmpeg joining, noise gating, ACX normalization, and final export."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pydub import AudioSegment

from config import (
    ACX_NOISE_FLOOR_DB,
    ACX_PEAK_MAX_DB,
    ACX_PEAK_TARGET_DB,
    ACX_RMS_MAX_DB,
    ACX_RMS_MIN_DB,
    ACX_RMS_TARGET_DB,
    CHANNELS,
    CROSSFADE_MS,
    EXPORT_MP3_BITRATE,
    NOISE_GATE_DB,
    OUTPUT_FINAL_DIR,
    OUTPUT_REPORTS_DIR,
    SAMPLE_RATE,
    SILENCE_BETWEEN_SEG_MS,
    SILENCE_CHAPTER_END_MS,
)


def _dtype_for_sample_width(sample_width: int):
    if sample_width == 1:
        return np.int8
    if sample_width == 2:
        return np.int16
    if sample_width == 4:
        return np.int32
    raise ValueError(f"Unsupported sample width: {sample_width}")


def load_segments_from_manifest(manifest_path: str) -> list[AudioSegment]:
    """Load successful synthesized segments ordered by segment index."""
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)

    valid_items = sorted(
        [
            item
            for item in manifest
            if item.get("synthesis_status") == "success"
            and item.get("audio_path")
            and Path(str(item["audio_path"])).exists()
        ],
        key=lambda item: int(item["segment_index"]),
    )
    if not valid_items:
        raise RuntimeError("No successful synthesized segments found in manifest.")

    segments: list[AudioSegment] = []
    for item in valid_items:
        audio = AudioSegment.from_file(str(item["audio_path"]))
        if audio.channels != CHANNELS:
            audio = audio.set_channels(CHANNELS)
        if audio.frame_rate != SAMPLE_RATE:
            audio = audio.set_frame_rate(SAMPLE_RATE)
        segments.append(audio)
    return segments


def join_segments(segments: list[AudioSegment]) -> AudioSegment:
    """Join synthesized segments with configured silence and crossfade."""
    if not segments:
        raise RuntimeError("Cannot join zero segments.")

    silence_between = AudioSegment.silent(duration=SILENCE_BETWEEN_SEG_MS, frame_rate=SAMPLE_RATE)
    combined = segments[0]
    for segment in segments[1:]:
        combined = combined.append(silence_between, crossfade=0)
        combined = combined.append(segment, crossfade=CROSSFADE_MS)
    combined += AudioSegment.silent(duration=SILENCE_CHAPTER_END_MS, frame_rate=SAMPLE_RATE)
    return combined


def apply_noise_gate(audio: AudioSegment, threshold_db: float = NOISE_GATE_DB, attenuation: float = 0.15) -> AudioSegment:
    """Attenuate very low-level samples to reduce background floor noise."""
    dtype = _dtype_for_sample_width(audio.sample_width)
    max_abs = float(2 ** (8 * audio.sample_width - 1) - 1)
    threshold_linear = 10 ** (threshold_db / 20.0)

    samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
    normalized = samples / max_abs
    quiet_mask = np.abs(normalized) < threshold_linear
    normalized[quiet_mask] *= attenuation
    processed = np.clip(normalized * max_abs, -max_abs, max_abs).astype(dtype)
    return audio._spawn(processed.tobytes())


def analyze_audio(audio: AudioSegment) -> dict:
    """Measure RMS, peak, and estimated noise floor with ACX pass checks."""
    max_abs = float(2 ** (8 * audio.sample_width - 1) - 1)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / max_abs

    rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    quiet_slice = np.sort(np.abs(samples))[: max(1, int(len(samples) * 0.10))]
    quiet_rms = float(np.sqrt(np.mean(np.square(quiet_slice)))) if len(quiet_slice) else 0.0

    rms_db = 20 * np.log10(rms) if rms > 1e-10 else -120.0
    peak_db = 20 * np.log10(peak) if peak > 1e-10 else -120.0
    noise_floor_db = 20 * np.log10(quiet_rms) if quiet_rms > 1e-10 else -120.0

    rms_pass = ACX_RMS_MIN_DB <= rms_db <= ACX_RMS_MAX_DB
    peak_pass = peak_db <= ACX_PEAK_MAX_DB
    noise_pass = noise_floor_db <= ACX_NOISE_FLOOR_DB
    return {
        "rms_db": round(rms_db, 2),
        "peak_db": round(peak_db, 2),
        "noise_floor_db": round(noise_floor_db, 2),
        "rms_pass": rms_pass,
        "peak_pass": peak_pass,
        "noise_pass": noise_pass,
        "acx_pass": bool(rms_pass and peak_pass and noise_pass),
        "duration_sec": round(len(audio) / 1000.0, 1),
    }


def normalize_to_acx(audio: AudioSegment) -> AudioSegment:
    """Iteratively normalize RMS and clamp peak to ACX working targets."""
    working = audio
    for _ in range(4):
        metrics = analyze_audio(working)
        gain = ACX_RMS_TARGET_DB - metrics["rms_db"]
        if abs(gain) < 0.15:
            break
        working = working.apply_gain(gain)

    metrics = analyze_audio(working)
    if metrics["peak_db"] > ACX_PEAK_TARGET_DB:
        working = working.apply_gain(ACX_PEAK_TARGET_DB - metrics["peak_db"])
    return working


def export_final(audio: AudioSegment, book_title: str) -> dict:
    """Export final mastered files in MP3 and FLAC."""
    output_final = Path(OUTPUT_FINAL_DIR)
    output_final.mkdir(parents=True, exist_ok=True)

    mp3_path = output_final / f"{book_title}_final.mp3"
    flac_path = output_final / f"{book_title}_final.flac"
    audio.export(mp3_path, format="mp3", bitrate=EXPORT_MP3_BITRATE)
    audio.export(flac_path, format="flac")

    return {"mp3_path": str(mp3_path), "flac_path": str(flac_path)}


def save_report(analysis: dict, book_title: str) -> str:
    """Save ACX analysis report."""
    output_reports = Path(OUTPUT_REPORTS_DIR)
    output_reports.mkdir(parents=True, exist_ok=True)
    report_path = output_reports / f"{book_title}_acx_report.json"
    with open(report_path, "w", encoding="utf-8") as report_file:
        json.dump(analysis, report_file, ensure_ascii=False, indent=2)
    return str(report_path)


def run_postproduction(manifest_path: str, book_title: str) -> dict:
    """Execute postproduction flow from manifest to ACX report."""
    print(f"[POSTPRODUCTION] {book_title}")
    segments = load_segments_from_manifest(manifest_path)
    joined = join_segments(segments)
    gated = apply_noise_gate(joined)
    normalized = normalize_to_acx(gated)
    analysis = analyze_audio(normalized)
    exports = export_final(normalized, book_title)
    analysis.update(exports)
    analysis["report_path"] = save_report(analysis, book_title)
    return analysis
