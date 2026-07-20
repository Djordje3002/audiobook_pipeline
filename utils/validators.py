"""Segment-level translation validation and quality checks."""

from __future__ import annotations

import re

from config import TRANSLATION_MAX_RATIO, TRANSLATION_MIN_RATIO

SERBIAN_CHAR_RE = re.compile(r"[čćžšđČĆŽŠĐ]")
META_COMMENTARY_PATTERNS = (
    "translation:",
    "translated text:",
    "here is the translation",
    "note:",
    "as an ai",
    "i translated",
)


def _contains_serbian_chars(text: str) -> bool:
    return bool(SERBIAN_CHAR_RE.search(text))


def _has_meta_commentary(text_lower: str) -> bool:
    return any(pattern in text_lower for pattern in META_COMMENTARY_PATTERNS)


def _missing_protected_names(original_text: str, translated_text: str, glossary: dict) -> list[str]:
    missing_names = []
    protected_names = glossary.get("names", []) if isinstance(glossary, dict) else []
    original_lower = original_text.lower()
    translated_lower = translated_text.lower()

    for name in protected_names:
        name_clean = str(name).strip()
        if not name_clean:
            continue
        name_lower = name_clean.lower()
        if name_lower in original_lower and name_lower not in translated_lower:
            missing_names.append(name_clean)
    return missing_names


def validate_translation(
    segment: dict,
    glossary: dict | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
) -> list[str]:
    """Return non-blocking warnings for translation quality checks."""
    warnings: list[str] = []

    original_text = str(segment.get("original_text", "")).strip()
    translated_text = str(segment.get("translated_text", "")).strip()

    if not translated_text:
        warnings.append("Translation is empty.")
        return warnings

    source_code = str(source_language or "").lower()
    target_code = str(target_language or "").lower()
    bcs_codes = {"sr", "bs", "hr"}
    if source_code in bcs_codes and target_code and target_code not in bcs_codes and _contains_serbian_chars(translated_text):
        warnings.append("Translated output still contains Serbian-specific characters.")

    translated_lower = translated_text.lower()
    if _has_meta_commentary(translated_lower):
        warnings.append("Translated output appears to contain model commentary/meta text.")

    if original_text:
        ratio = len(translated_text) / max(1, len(original_text))
        if ratio < TRANSLATION_MIN_RATIO or ratio > TRANSLATION_MAX_RATIO:
            warnings.append(
                f"Translation length ratio {ratio:.2f} is outside expected range "
                f"({TRANSLATION_MIN_RATIO:.2f} - {TRANSLATION_MAX_RATIO:.2f})."
            )

    if glossary:
        missing_names = _missing_protected_names(original_text, translated_text, glossary)
        if missing_names:
            warnings.append(
                "Protected names possibly missing in translation: "
                + ", ".join(missing_names[:10])
            )

    return warnings
