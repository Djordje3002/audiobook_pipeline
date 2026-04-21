"""Flask web server entrypoint and job management routes."""

from flask import Flask, jsonify, render_template, request

from auth import require_basic_auth
from main import run_full_book, run_preview

app = Flask(__name__)


@app.get("/")
@require_basic_auth
def index():
    return render_template("index.html")


@app.post("/api/preview")
@require_basic_auth
def preview():
    payload = request.get_json(silent=True) or {}
    source_path = payload.get("source_path", "")
    result = run_preview(source_path)
    return jsonify(result)


@app.post("/api/full")
@require_basic_auth
def full_book():
    payload = request.get_json(silent=True) or {}
    source_path = payload.get("source_path", "")
    result = run_full_book(source_path)
    return jsonify(result)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
