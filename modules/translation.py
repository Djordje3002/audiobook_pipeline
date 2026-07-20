"""Literary translation through the OpenAI Responses API and glossary extraction."""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from openai import OpenAI
from tqdm import tqdm

from config import (
    AUTHOR_STYLE,
    BOOK_GENRE,
    OPENAI_MODEL,
    OPENAI_REASONING_EFFORT,
    OPENAI_RETRY_COUNT,
    OUTPUT_TRANSLATED_DIR,
    REQUEST_DELAY_SEC,
    OPENAI_API_KEY,
)
from modules.languages import language_name, normalize_language_code
from utils.validators import validate_translation

NAME_RE = re.compile(r"\b[A-ZČĆŽŠĐ][a-zčćžšđ]{2,}\b")
TOKEN_RE = re.compile(r"[A-Za-zČĆŽŠĐčćžšđ]{3,}")


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


def extract_glossary(segments: list[dict], top_names: int = 30, top_phrases: int = 25) -> dict:
    """Extract lightweight glossary artifacts from source text."""
    original_texts = [str(seg.get("original_text") or seg.get("text") or "").strip() for seg in segments]
    joined_text = " ".join(text for text in original_texts if text)

    name_counter = Counter(NAME_RE.findall(joined_text))
    names = [name for name, _count in name_counter.most_common(top_names)]

    words = [token.lower() for token in TOKEN_RE.findall(joined_text)]
    bigrams = Counter(" ".join(words[idx : idx + 2]) for idx in range(max(0, len(words) - 1)))
    recurring_phrases = [phrase for phrase, count in bigrams.most_common(top_phrases) if count >= 3]

    return {
        "names": names,
        "phrases": recurring_phrases,
        "style_notes": [
            f"Genre: {BOOK_GENRE}",
            f"Author style target: {AUTHOR_STYLE}",
            "Keep character voice consistent and avoid modernizing period tone.",
        ],
    }


def save_glossary(glossary: dict, book_title: str) -> str:
    """Persist extracted glossary to JSON."""
    os.makedirs(OUTPUT_TRANSLATED_DIR, exist_ok=True)
    glossary_path = Path(OUTPUT_TRANSLATED_DIR) / f"{book_title}_glossary.json"
    with open(glossary_path, "w", encoding="utf-8") as output_file:
        json.dump(glossary, output_file, ensure_ascii=False, indent=2)
    print(f"  Saved glossary: {glossary_path}")
    return str(glossary_path)


def build_system_prompt(
    glossary: dict,
    source_language: str = "sr",
    target_language: str = "en",
) -> str:
    """Construct the literary translation system prompt."""
    source_code = normalize_language_code(source_language, allow_auto=True)
    target_code = normalize_language_code(target_language)
    source_name = language_name(source_code)
    target_name = language_name(target_code)
    names = ", ".join(glossary.get("names", [])[:40]) or "None detected"
    phrases = ", ".join(glossary.get("phrases", [])[:25]) or "None detected"
    style_notes = "\n".join(f"- {note}" for note in glossary.get("style_notes", []))

    return (
        f"You are a professional literary translator working from {source_name} to {target_name}.\n\n"
        f"GENRE: {BOOK_GENRE}\n"
        f"AUTHOR STYLE: {AUTHOR_STYLE}\n\n"
        "GLOSSARY:\n"
        f"Character names and protected names: {names}\n"
        f"Recurring phrases: {phrases}\n"
        f"Style notes:\n{style_notes}\n\n"
        "RULES:\n"
        "1. Preserve narrative rhythm, tone, and emotional intensity.\n"
        f"2. Use idiomatic {target_name} equivalents for slang and expressions.\n"
        "3. Do not output commentary, labels, or explanations.\n"
        "4. Keep names and recurring terminology consistent.\n"
        "5. Return only translated prose suitable for voice synthesis."
    )


def translate_segment(
    client: OpenAI,
    segment: dict,
    glossary: dict,
    source_language: str = "sr",
    target_language: str = "en",
    safety_identifier: str | None = None,
    retry_count: int = OPENAI_RETRY_COUNT,
) -> dict:
    """Translate one segment with retries and structured result fields."""
    for attempt in range(retry_count):
        try:
            request_options = {
                "model": OPENAI_MODEL,
                "instructions": build_system_prompt(
                    glossary,
                    source_language=source_language,
                    target_language=target_language,
                ),
                "input": (
                    f"Translate the following prose into {language_name(target_language)}. "
                    "Return only the translated prose.\n\n"
                    f"{segment['original_text']}"
                ),
                "max_output_tokens": 2000,
                "reasoning": {"effort": OPENAI_REASONING_EFFORT},
                "text": {"verbosity": "low"},
                "store": False,
            }
            if safety_identifier:
                request_options["safety_identifier"] = safety_identifier

            response = client.responses.create(**request_options)
            translated_text = str(response.output_text or "").strip()
            usage = getattr(response, "usage", None)
            total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

            result = {
                **segment,
                "translated_text": translated_text,
                "tokens_used": total_tokens,
                "translation_status": "success",
            }
            result["validation_warnings"] = validate_translation(
                result,
                glossary=glossary,
                source_language=source_language,
                target_language=target_language,
            )
            return result
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  Translation attempt {attempt + 1}/{retry_count} failed: {exc}")
            if attempt < retry_count - 1:
                time.sleep(2**attempt)

    failed_result = {
        **segment,
        "translated_text": "",
        "tokens_used": 0,
        "translation_status": "failed",
        "validation_warnings": ["Translation request failed after retries."],
    }
    return failed_result


def _load_existing_translations(output_path: Path) -> dict[int, dict]:
    if not output_path.exists():
        return {}

    with open(output_path, "r", encoding="utf-8") as input_file:
        data = json.load(input_file)
    by_index: dict[int, dict] = {}
    for item in data:
        by_index[int(item["segment_index"])] = item
    return by_index


def _write_translations(output_path: Path, by_index: dict[int, dict]) -> None:
    ordered = [by_index[idx] for idx in sorted(by_index)]
    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(ordered, output_file, ensure_ascii=False, indent=2)


def translate_all_segments(
    segments: list[dict],
    book_title: str,
    glossary: dict | None = None,
    openai_api_key: str | None = None,
    source_language: str = "sr",
    target_language: str = "en",
    safety_identifier: str | None = None,
) -> list[dict]:
    """Translate segments with resume support and incremental persistence."""
    client = _get_client(api_key=openai_api_key)
    os.makedirs(OUTPUT_TRANSLATED_DIR, exist_ok=True)
    output_path = Path(OUTPUT_TRANSLATED_DIR) / f"{book_title}_translated.json"

    active_glossary = glossary if glossary is not None else extract_glossary(segments)
    save_glossary(active_glossary, book_title)

    by_index = _load_existing_translations(output_path)
    done_indices = {
        idx
        for idx, item in by_index.items()
        if item.get("translation_status") == "success" and str(item.get("translated_text", "")).strip()
    }
    if done_indices:
        print(f"  Resume detected: {len(done_indices)} segments already translated")

    print(f"[TRANSLATION] Processing {len(segments)} segments")
    for segment in tqdm(segments, desc="  Translate", unit="segment"):
        segment_index = int(segment["segment_index"])
        if segment_index in done_indices:
            continue

        translated_segment = translate_segment(
            client=client,
            segment=segment,
            glossary=active_glossary,
            source_language=source_language,
            target_language=target_language,
            safety_identifier=safety_identifier,
        )
        by_index[segment_index] = translated_segment
        _write_translations(output_path, by_index)
        time.sleep(REQUEST_DELAY_SEC)

    ordered = [by_index[idx] for idx in sorted(by_index)]
    failed_count = sum(1 for item in ordered if item.get("translation_status") != "success")
    warning_count = sum(len(item.get("validation_warnings", [])) for item in ordered)
    if failed_count:
        print(f"  Warning: {failed_count} segments failed translation")
    if warning_count:
        print(f"  Validation warnings: {warning_count}")
    return ordered
