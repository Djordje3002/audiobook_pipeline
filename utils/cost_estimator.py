"""Pre-run cost calculator for transcription, translation, and synthesis."""


def estimate_cost(hours: float) -> float:
    """Rough baseline estimate using the provided 6h ~= $45 reference."""
    if hours <= 0:
        return 0.0
    return round((45.0 / 6.0) * hours, 2)
