"""Product language catalog and normalization helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native_name: str
    source_enabled: bool = True
    target_enabled: bool = True


LANGUAGES = (
    Language("ar", "Arabic", "العربية"),
    Language("bs", "Bosnian", "Bosanski"),
    Language("bg", "Bulgarian", "Български"),
    Language("zh", "Chinese", "中文"),
    Language("hr", "Croatian", "Hrvatski"),
    Language("cs", "Czech", "Čeština"),
    Language("da", "Danish", "Dansk"),
    Language("nl", "Dutch", "Nederlands"),
    Language("en", "English", "English"),
    Language("fi", "Finnish", "Suomi"),
    Language("fr", "French", "Français"),
    Language("de", "German", "Deutsch"),
    Language("el", "Greek", "Ελληνικά"),
    Language("he", "Hebrew", "עברית"),
    Language("hi", "Hindi", "हिन्दी"),
    Language("hu", "Hungarian", "Magyar"),
    Language("id", "Indonesian", "Bahasa Indonesia"),
    Language("it", "Italian", "Italiano"),
    Language("ja", "Japanese", "日本語"),
    Language("ko", "Korean", "한국어"),
    Language("mk", "Macedonian", "Македонски"),
    Language("no", "Norwegian", "Norsk"),
    Language("pl", "Polish", "Polski"),
    Language("pt", "Portuguese", "Português"),
    Language("ro", "Romanian", "Română"),
    Language("ru", "Russian", "Русский"),
    Language("sr", "Serbian", "Српски / Srpski"),
    Language("sk", "Slovak", "Slovenčina"),
    Language("sl", "Slovenian", "Slovenščina"),
    Language("es", "Spanish", "Español"),
    Language("sv", "Swedish", "Svenska"),
    Language("tr", "Turkish", "Türkçe"),
    Language("uk", "Ukrainian", "Українська"),
    Language("vi", "Vietnamese", "Tiếng Việt"),
)

LANGUAGE_BY_CODE = {language.code: language for language in LANGUAGES}


def normalize_language_code(value: str | None, *, allow_auto: bool = False) -> str:
    """Normalize and validate a language code against the product catalog."""
    code = str(value or "").strip().lower().replace("_", "-")
    if allow_auto and code == "auto":
        return code
    if code not in LANGUAGE_BY_CODE:
        raise ValueError(f"Unsupported language code: {code or '(empty)'}")
    return code


def language_name(code: str) -> str:
    """Return a prompt-safe language name, including automatic detection."""
    if code == "auto":
        return "the detected source language"
    return LANGUAGE_BY_CODE[normalize_language_code(code)].name


def language_catalog() -> list[dict]:
    """Return the public language catalog in stable display order."""
    return [asdict(language) for language in LANGUAGES]
