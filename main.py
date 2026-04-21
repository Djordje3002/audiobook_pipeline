"""Pipeline orchestrator for preview and full-book production."""

from utils.cost_estimator import estimate_cost


def run_preview(source_path: str) -> dict:
    """Run only the first five minutes through the full pipeline."""
    return {
        "mode": "preview",
        "source_path": source_path,
        "estimated_cost_usd": estimate_cost(hours=0.0833),
        "status": "queued",
    }


def run_full_book(source_path: str) -> dict:
    """Run the entire audiobook pipeline end-to-end."""
    return {
        "mode": "full",
        "source_path": source_path,
        "status": "queued",
    }
