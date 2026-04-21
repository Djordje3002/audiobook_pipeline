"""Flask web server entrypoint and job management routes."""

from __future__ import annotations

import json
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from auth import require_auth
from config import INPUT_AUDIO_DIR, OUTPUT_TRANSLATED_DIR
from main import run_full_book, run_preview

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
TRANSLATED_ROOT = (BASE_DIR / OUTPUT_TRANSLATED_DIR).resolve()
MEDIA_ROOTS = (
    BASE_DIR / "output_audio",
    BASE_DIR / "output",
    BASE_DIR / "input_audio",
)


def _frontend_index_exists() -> bool:
    return (FRONTEND_DIST_DIR / "index.html").exists()


def _is_within_allowed_media_roots(candidate_path: Path) -> bool:
    resolved = candidate_path.resolve()
    for root in MEDIA_ROOTS:
        root_resolved = root.resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return True
    return False


def _resolve_translated_artifact_path(raw_path: str | None) -> Path:
    if not raw_path or not str(raw_path).strip():
        raise ValueError("translated_path is required.")

    candidate = Path(str(raw_path).strip())
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    resolved = candidate.resolve()

    if not str(resolved).endswith(".json"):
        raise ValueError("translated_path must point to a JSON file.")
    if resolved != TRANSLATED_ROOT and TRANSLATED_ROOT not in resolved.parents:
        raise ValueError("translated_path must be inside output/translated/.")
    return resolved


@app.get("/")
@require_auth
def index():
    if _frontend_index_exists():
        return send_from_directory(FRONTEND_DIST_DIR, "index.html")
    return render_template("index.html")


@app.post("/api/upload")
@require_auth
def upload():
    if "file" not in request.files:
        return jsonify({"status": "error", "error": "Missing file in multipart form-data."}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"status": "error", "error": "No file selected."}), 400

    safe_name = secure_filename(uploaded_file.filename)
    if not safe_name:
        return jsonify({"status": "error", "error": "Filename is invalid."}), 400

    input_dir = Path(INPUT_AUDIO_DIR)
    input_dir.mkdir(parents=True, exist_ok=True)

    target_path = input_dir / safe_name
    if target_path.exists():
        timestamp = int(time.time())
        target_path = input_dir / f"{target_path.stem}_{timestamp}{target_path.suffix}"

    uploaded_file.save(target_path)
    source_path = str(target_path).replace("\\", "/")
    return jsonify(
        {
            "status": "success",
            "filename": target_path.name,
            "source_path": source_path,
            "size_bytes": target_path.stat().st_size,
        }
    )


@app.post("/api/preview")
@require_auth
def preview():
    payload = request.get_json(silent=True) or {}
    source_path = payload.get("source_path", "")
    if not str(source_path).strip():
        return jsonify({"status": "error", "error": "source_path is required."}), 400
    book_title = payload.get("book_title")
    result = run_preview(source_path, book_title=book_title)
    return jsonify(result)


@app.post("/api/full")
@require_auth
def full_book():
    payload = request.get_json(silent=True) or {}
    source_path = payload.get("source_path", "")
    if not str(source_path).strip():
        return jsonify({"status": "error", "error": "source_path is required."}), 400
    book_title = payload.get("book_title")
    skip_transcription = bool(payload.get("skip_transcription", False))
    result = run_full_book(
        source_path,
        book_title=book_title,
        skip_transcription=skip_transcription,
    )
    return jsonify(result)


@app.post("/api/save-translated")
@require_auth
def save_translated():
    payload = request.get_json(silent=True) or {}
    translated_path = payload.get("translated_path")
    segments = payload.get("segments")

    if not isinstance(segments, list):
        return jsonify({"status": "error", "error": "segments must be a JSON array."}), 400

    try:
        output_path = _resolve_translated_artifact_path(translated_path)
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400

    if not output_path.exists():
        return jsonify({"status": "error", "error": "Translated artifact does not exist on disk."}), 404

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(segments, output_file, ensure_ascii=False, indent=2)

    return jsonify(
        {
            "status": "success",
            "translated_path": str(output_path.relative_to(BASE_DIR)).replace("\\", "/"),
            "segments_saved": len(segments),
            "saved_at": int(time.time()),
        }
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/media/<path:file_path>")
@require_auth
def media(file_path: str):
    requested = (BASE_DIR / file_path).resolve()
    if not requested.exists() or not requested.is_file():
        return jsonify({"status": "error", "error": "File not found."}), 404
    if not _is_within_allowed_media_roots(requested):
        return jsonify({"status": "error", "error": "Access denied for this path."}), 403
    return send_from_directory(requested.parent, requested.name)


@app.get("/<path:path>")
@require_auth
def frontend_assets(path: str):
    if not _frontend_index_exists():
        return jsonify({"status": "error", "error": "Frontend build not found. Run npm run build."}), 404

    candidate = FRONTEND_DIST_DIR / path
    if candidate.exists() and candidate.is_file():
        return send_from_directory(FRONTEND_DIST_DIR, path)
    return send_from_directory(FRONTEND_DIST_DIR, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
