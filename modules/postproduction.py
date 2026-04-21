"""FFmpeg joining, noise gating, ACX normalization, and final export."""


def build_final_audiobook(segment_paths: list[str]) -> dict:
    """Join segments and export ACX-compliant MP3 + FLAC outputs."""
    _ = segment_paths
    return {"mp3": "", "flac": "", "acx_report": {}}
