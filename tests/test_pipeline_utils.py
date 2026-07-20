"""Fast tests for deterministic pipeline helpers."""

from __future__ import annotations

from modules.audio_ingestion import group_segments
from modules.languages import language_catalog, normalize_language_code
from modules.translation import build_system_prompt
from utils.cost_estimator import estimate_cost
from utils.validators import validate_translation


def test_group_segments_respects_character_limit() -> None:
    grouped = group_segments(
        [
            {"start": 0.0, "end": 1.0, "text": "Prvi deo."},
            {"start": 1.0, "end": 2.0, "text": "Drugi deo."},
        ],
        max_chars=12,
    )

    assert len(grouped) == 2
    assert grouped[0]["segment_index"] == 0
    assert grouped[1]["start"] == 1.0


def test_translation_validator_flags_empty_output() -> None:
    warnings = validate_translation({"original_text": "Zdravo", "translated_text": ""})

    assert warnings == ["Translation is empty."]


def test_cost_estimate_baseline() -> None:
    assert estimate_cost(6) == 45.0
    assert estimate_cost(0) == 0.0


def test_multilingual_catalog_and_prompt() -> None:
    codes = {language["code"] for language in language_catalog()}
    assert {"sr", "en", "de", "es", "fr", "ja", "ar"}.issubset(codes)
    assert normalize_language_code("AUTO", allow_auto=True) == "auto"

    prompt = build_system_prompt({}, source_language="sr", target_language="de")
    assert "Serbian to German" in prompt
    assert "idiomatic German" in prompt
