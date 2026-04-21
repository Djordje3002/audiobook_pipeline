"""Flask web server entrypoint and job management routes."""

from flask import Flask, jsonify, render_template, request

from auth import require_auth
from main import run_full_book, run_preview

app = Flask(__name__)


@app.get("/")
@require_auth
def index():
    return render_template("index.html")


@app.post("/api/preview")
@require_auth
def preview():
    payload = request.get_json(silent=True) or {}
    source_path = payload.get("source_path", "")
    book_title = payload.get("book_title")
    result = run_preview(source_path, book_title=book_title)
    return jsonify(result)


@app.post("/api/full")
@require_auth
def full_book():
    payload = request.get_json(silent=True) or {}
    source_path = payload.get("source_path", "")
    book_title = payload.get("book_title")
    skip_transcription = bool(payload.get("skip_transcription", False))
    result = run_full_book(
        source_path,
        book_title=book_title,
        skip_transcription=skip_transcription,
    )
    return jsonify(result)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
