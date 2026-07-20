"""Pipeline orchestrator for preview and full-book production."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydub import AudioSegment

from config import (
    OUTPUT_AUDIO_DIR,
    OUTPUT_PREVIEW_DIR,
    OUTPUT_TRANSLATED_DIR,
    OPENAI_API_KEY,
    PREVIEW_MINUTES,
    TEMP_CHUNKS_DIR,
)
from modules.audio_ingestion import group_segments, save_transcript, transcribe_audio
from modules.languages import language_name, normalize_language_code
from modules.postproduction import join_segments, run_postproduction
from modules.synthesis import synthesize_all_segments
from modules.translation import extract_glossary, save_glossary, translate_all_segments


def _derive_book_title(source_path: str, explicit_book_title: str | None = None) -> str:
    if explicit_book_title and explicit_book_title.strip():
        return explicit_book_title.strip().replace(" ", "_")
    return Path(source_path).stem.replace(" ", "_")


def _resolve_openai_api_key(openai_api_key: str | None = None) -> str:
    resolved = str(openai_api_key or OPENAI_API_KEY or "").strip()
    if not resolved:
        raise RuntimeError(
            "Missing OpenAI API key. Paste your key in the OpenAI field in the web app, "
            "or set OPENAI_API_KEY in .env for CLI usage."
        )
    return resolved


def _load_existing_transcript(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as transcript_file:
        return json.load(transcript_file)


def _estimate_costs(segments: list[dict], duration_sec: float) -> dict:
    total_chars = sum(len(str(item.get("original_text", ""))) for item in segments)
    whisper_cost = (duration_sec / 60.0) * 0.006
    gpt_cost = (total_chars / 1_000_000.0) * 20.0
    total_cost = whisper_cost + gpt_cost
    return {
        "duration_min": round(duration_sec / 60.0, 2),
        "segments": len(segments),
        "characters": total_chars,
        "whisper_usd": round(whisper_cost, 2),
        "gpt_translation_usd": round(gpt_cost, 2),
        "voice_stage_status": "disabled_for_mvp",
        "voice_stage_usd": 0.0,
        "total_usd": round(total_cost, 2),
    }


def _print_cost_breakdown(costs: dict) -> None:
    print("\n" + "=" * 60)
    print("COST ESTIMATE")
    print("=" * 60)
    print(f"  Duration:      {costs['duration_min']:.2f} min")
    print(f"  Segments:      {costs['segments']}")
    print(f"  Characters:    {costs['characters']:,}")
    print(f"  Whisper:       ~${costs['whisper_usd']:.2f}")
    print(f"  Translation:   ~${costs['gpt_translation_usd']:.2f}")
    print("  ElevenLabs:    disabled for MVP (text-only mode)")
    print("  -------------------------------")
    print(f"  TOTAL:         ~${costs['total_usd']:.2f}")
    print("=" * 60)


def _confirm_cli(prompt: str) -> bool:
    response = input(prompt).strip().lower()
    return response in {"y", "yes"}


def _create_preview_source(input_audio: str, book_title: str) -> str:
    preview_seconds = PREVIEW_MINUTES * 60
    preview_output = Path(TEMP_CHUNKS_DIR) / f"{book_title}_preview_source.mp3"
    preview_output.parent.mkdir(parents=True, exist_ok=True)

    source_audio = AudioSegment.from_file(input_audio)
    preview_audio = source_audio[: int(preview_seconds * 1000)]
    preview_audio.export(preview_output, format="mp3", bitrate="192k")
    return str(preview_output)


def _build_preview_file(manifest_items: list[dict], book_title: str) -> str:
    success_items = sorted(
        [
            item
            for item in manifest_items
            if item.get("synthesis_status") == "success"
            and item.get("audio_path")
            and Path(str(item["audio_path"])).exists()
        ],
        key=lambda item: int(item["segment_index"]),
    )
    if not success_items:
        raise RuntimeError("Preview failed: no synthesized segments were produced.")

    segment_audio = [AudioSegment.from_file(str(item["audio_path"])) for item in success_items]
    preview_audio = join_segments(segment_audio)

    output_dir = Path(OUTPUT_PREVIEW_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = output_dir / f"{book_title}_preview.mp3"
    preview_audio.export(preview_path, format="mp3", bitrate="192k")
    return str(preview_path)


def run(
    input_audio: str,
    book_title: str,
    preview_only: bool = False,
    skip_transcription: bool = False,
    require_confirmation: bool = True,
    openai_api_key: str | None = None,
    source_language: str = "sr",
    target_language: str = "en",
    safety_identifier: str | None = None,
) -> dict:
    """Run preview or full production pipeline and return artifact metadata."""
    resolved_openai_api_key = _resolve_openai_api_key(openai_api_key)
    source_code = normalize_language_code(source_language, allow_auto=True)
    target_code = normalize_language_code(target_language)
    if source_code == target_code:
        raise ValueError("Source and target languages must be different.")

    input_path = Path(input_audio)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_audio}")

    print("\n" + "=" * 60)
    print("AUDIOBOOK PIPELINE")
    print(f"Input file: {input_audio}")
    print(f"Book title: {book_title}")
    print(f"Languages:  {language_name(source_code)} -> {language_name(target_code)}")
    print(f"Mode:       {'Preview translation (first 5 min)' if preview_only else 'Full translation'}")
    print("=" * 60)

    mode_key = f"{book_title}_preview" if preview_only else book_title
    source_artifact_key = f"{mode_key}_{source_code}"
    translation_artifact_key = f"{source_artifact_key}_to_{target_code}"
    processing_input = _create_preview_source(str(input_path), book_title) if preview_only else str(input_path)

    transcript_path = Path(OUTPUT_TRANSLATED_DIR) / f"{source_artifact_key}_transcript.json"
    if skip_transcription and transcript_path.exists():
        print(f"[0/3] Loading existing transcript: {transcript_path}")
        grouped_segments = _load_existing_transcript(transcript_path)
    else:
        print("[0/3] Transcribing source audio with Whisper...")
        raw_segments = transcribe_audio(
            processing_input,
            api_key=resolved_openai_api_key,
            source_language=source_code,
        )
        grouped_segments = group_segments(raw_segments)
        save_transcript(grouped_segments, source_artifact_key)

    if not grouped_segments:
        raise RuntimeError("No transcript segments were generated.")

    duration_sec = float(grouped_segments[-1]["end"])
    costs = _estimate_costs(grouped_segments, duration_sec)
    _print_cost_breakdown(costs)
    if require_confirmation and not _confirm_cli("\nContinue? [y/N]: "):
        return {"status": "cancelled", "reason": "User cancelled after cost estimate."}

    print("[1/3] Building and saving glossary...")
    glossary = extract_glossary(grouped_segments)
    glossary_path = save_glossary(glossary, translation_artifact_key)

    print("[2/3] Translating grouped segments...")
    translated_segments = translate_all_segments(
        grouped_segments,
        translation_artifact_key,
        glossary=glossary,
        openai_api_key=resolved_openai_api_key,
        source_language=source_code,
        target_language=target_code,
        safety_identifier=safety_identifier,
    )
    translated_path = str(
        Path(OUTPUT_TRANSLATED_DIR) / f"{translation_artifact_key}_translated.json"
    )

    if preview_only:
        print("[3/3] Translation preview completed.")

        # TODO(re-enable-voice-stage): Restore ElevenLabs preview synthesis once budget allows.
        # print("[3/5] Synthesizing preview segments...")
        # preview_manifest = synthesize_all_segments(
        #     segments=translated_segments,
        #     original_audio_path=processing_input,
        #     book_title=artifact_key,
        # )
        # preview_path = _build_preview_file(preview_manifest, book_title)
        # print(f"Preview ready: {preview_path}")

        return {
            "status": "success",
            "mode": "preview",
            "book_title": book_title,
            "source_language": source_code,
            "target_language": target_code,
            "transcript_path": str(transcript_path),
            "glossary_path": glossary_path,
            "translated_path": translated_path,
            "translated_segments_count": len(translated_segments),
            "voice_stage": "disabled_for_mvp",
            "cost_estimate": costs,
        }

    print("[3/3] Full translation completed.")

    # TODO(re-enable-voice-stage): Restore full ElevenLabs + ACX pipeline once budget allows.
    # if require_confirmation and not _confirm_cli("\nStart full synthesis now? [y/N]: "):
    #     return {"status": "cancelled", "reason": "User cancelled before synthesis."}
    #
    # print("[3/5] Synthesizing translated segments with ElevenLabs...")
    # synthesize_all_segments(
    #     segments=translated_segments,
    #     original_audio_path=str(input_path),
    #     book_title=artifact_key,
    # )
    # manifest_path = Path(OUTPUT_AUDIO_DIR) / f"{artifact_key}_manifest.json"
    #
    # print("[4/5] Running postproduction and ACX verification...")
    # post_result = run_postproduction(str(manifest_path), book_title)
    #
    # print("[5/5] Pipeline finished successfully.")

    return {
        "status": "success",
        "mode": "full",
        "book_title": book_title,
        "source_language": source_code,
        "target_language": target_code,
        "transcript_path": str(transcript_path),
        "glossary_path": glossary_path,
        "translated_path": translated_path,
        "translated_segments_count": len(translated_segments),
        "voice_stage": "disabled_for_mvp",
        "cost_estimate": costs,
    }


def run_preview(
    source_path: str,
    book_title: str | None = None,
    openai_api_key: str | None = None,
    skip_transcription: bool = False,
    source_language: str = "sr",
    target_language: str = "en",
    safety_identifier: str | None = None,
) -> dict:
    """Wrapper used by Flask endpoint for preview mode."""
    resolved_title = _derive_book_title(source_path, book_title)
    try:
        return run(
            input_audio=source_path,
            book_title=resolved_title,
            preview_only=True,
            skip_transcription=skip_transcription,
            require_confirmation=False,
            openai_api_key=openai_api_key,
            source_language=source_language,
            target_language=target_language,
            safety_identifier=safety_identifier,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return {"status": "error", "mode": "preview", "error": str(exc)}


def run_full_book(
    source_path: str,
    book_title: str | None = None,
    skip_transcription: bool = False,
    openai_api_key: str | None = None,
    source_language: str = "sr",
    target_language: str = "en",
    safety_identifier: str | None = None,
) -> dict:
    """Wrapper used by Flask endpoint for full production mode."""
    resolved_title = _derive_book_title(source_path, book_title)
    try:
        return run(
            input_audio=source_path,
            book_title=resolved_title,
            preview_only=False,
            skip_transcription=skip_transcription,
            require_confirmation=False,
            openai_api_key=openai_api_key,
            source_language=source_language,
            target_language=target_language,
            safety_identifier=safety_identifier,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return {"status": "error", "mode": "full", "error": str(exc)}


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multilingual audiobook localization pipeline")
    parser.add_argument("--input", default="input_audio/knjiga.mp3", help="Input audiobook path.")
    parser.add_argument("--book-title", default="", help="Book title slug for output files.")
    parser.add_argument("--source-language", default="sr", help="Source language code or auto.")
    parser.add_argument("--target-language", default="en", help="Target language code.")
    parser.add_argument(
        "--full-run",
        action="store_true",
        help="Run full production. Without this flag, preview mode is used.",
    )
    parser.add_argument(
        "--skip-transcription",
        action="store_true",
        help="Reuse existing transcript JSON if available.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmations in CLI mode.",
    )
    return parser


if __name__ == "__main__":
    cli_args = _build_arg_parser().parse_args()
    title = _derive_book_title(cli_args.input, cli_args.book_title)
    result = run(
        input_audio=cli_args.input,
        book_title=title,
        preview_only=not cli_args.full_run,
        skip_transcription=cli_args.skip_transcription,
        require_confirmation=not cli_args.yes,
        source_language=cli_args.source_language,
        target_language=cli_args.target_language,
    )
    print("\nResult:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
