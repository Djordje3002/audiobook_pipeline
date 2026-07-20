"""Plain-text and DOCX manuscript extraction and narration-aware segmentation."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from config import MAX_CHARS_PER_SEGMENT

DOCUMENT_SUFFIXES = {".txt", ".md", ".docx"}
NARRATION_WORDS_PER_MINUTE = 150


def extract_document_text(path: str | Path) -> str:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in DOCUMENT_SUFFIXES:
        raise ValueError("Supported manuscript formats are TXT, Markdown, and DOCX.")

    if suffix == ".docx":
        document = Document(str(source))
        raw_text = "\n\n".join(paragraph.text for paragraph in document.paragraphs)
    else:
        try:
            raw_text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text manuscripts must use UTF-8 encoding.") from exc

    text = re.sub(r"[ \t]+", " ", raw_text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 20:
        raise ValueError("The manuscript does not contain enough readable text.")
    return text


def manuscript_word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def estimate_narration_seconds(text: str) -> float:
    words = manuscript_word_count(text)
    return round(max(1.0, words / NARRATION_WORDS_PER_MINUTE * 60.0), 3)


def segment_document(text: str, max_chars: int = MAX_CHARS_PER_SEGMENT) -> list[dict]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = sentence
            elif len(sentence) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(
                    sentence[index : index + max_chars].strip()
                    for index in range(0, len(sentence), max_chars)
                )
            else:
                current = candidate
        if current and len(current) >= max_chars * 0.65:
            chunks.append(current)
            current = ""

    if current:
        chunks.append(current)

    elapsed = 0.0
    segments: list[dict] = []
    for index, chunk in enumerate(chunks):
        duration = max(1.0, manuscript_word_count(chunk) / NARRATION_WORDS_PER_MINUTE * 60.0)
        segments.append(
            {
                "segment_index": index,
                "chapter_num": 1,
                "start": round(elapsed, 3),
                "end": round(elapsed + duration, 3),
                "original_text": chunk,
            }
        )
        elapsed += duration
    return segments
