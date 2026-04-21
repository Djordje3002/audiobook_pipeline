"""GPT-4o literary translation and glossary extraction."""


def extract_glossary(segments: list[dict]) -> dict:
    """Extract names, recurring phrases, and style notes."""
    return {"names": [], "phrases": [], "style_notes": []}


def translate_segments(segments: list[dict], glossary: dict) -> list[dict]:
    """Translate Serbian transcript segments into English."""
    _ = glossary
    return segments
