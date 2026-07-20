"""Flask web server entrypoint and job management routes."""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path

import requests
from flask import Blueprint, Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from auth import require_auth
from config import INPUT_AUDIO_DIR, OUTPUT_TRANSLATED_DIR
from main import run_full_book, run_preview
from modules.languages import language_catalog, normalize_language_code
from modules.reader import synthesize_translation_readback, synthesize_translation_readback_elevenlabs
from saas.api_auth import auth_api
from saas.api_billing import billing_api
from saas.api_projects import projects_api
from saas.extensions import init_extensions

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
TRANSLATED_ROOT = (BASE_DIR / OUTPUT_TRANSLATED_DIR).resolve()
MEDIA_ROOTS = (
    BASE_DIR / "output_audio",
    BASE_DIR / "output",
    BASE_DIR / "input_audio",
)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAX_FINISHED_JOBS = 200
web = Blueprint("web", __name__)


def _frontend_index_exists() -> bool:
    return (FRONTEND_DIST_DIR / "index.html").exists()


def _now_ts() -> int:
    return int(time.time())


def _prune_finished_jobs_unlocked() -> None:
    finished = [
        (job_id, int(job.get("updated_at", 0)))
        for job_id, job in JOBS.items()
        if str(job.get("status", "")).lower() in {"success", "error"}
    ]
    if len(finished) <= MAX_FINISHED_JOBS:
        return
    finished.sort(key=lambda item: item[1])
    for job_id, _updated in finished[:-MAX_FINISHED_JOBS]:
        JOBS.pop(job_id, None)


def _create_job(
    mode: str,
    source_path: str,
    book_title: str | None = None,
    source_language: str = "sr",
    target_language: str = "en",
) -> str:
    job_id = uuid.uuid4().hex
    now = _now_ts()
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "mode": mode,
            "status": "queued",
            "source_path": source_path,
            "book_title": str(book_title or "").strip() or None,
            "source_language": source_language,
            "target_language": target_language,
            "error": None,
            "result": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        _prune_finished_jobs_unlocked()
    return job_id


def _update_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = _now_ts()


def _get_job_snapshot(job_id: str) -> dict | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


def _run_pipeline_job(
    *,
    job_id: str,
    mode: str,
    source_path: str,
    book_title: str | None,
    openai_api_key: str,
    skip_transcription: bool = False,
    source_language: str = "sr",
    target_language: str = "en",
) -> None:
    _update_job(job_id, status="running", started_at=_now_ts(), error=None)

    try:
        if mode == "preview":
            result = run_preview(
                source_path,
                book_title=book_title,
                openai_api_key=openai_api_key,
                source_language=source_language,
                target_language=target_language,
            )
        else:
            result = run_full_book(
                source_path,
                book_title=book_title,
                skip_transcription=skip_transcription,
                openai_api_key=openai_api_key,
                source_language=source_language,
                target_language=target_language,
            )
    except Exception as exc:  # pylint: disable=broad-except
        _update_job(
            job_id,
            status="error",
            finished_at=_now_ts(),
            error=f"{type(exc).__name__}: {exc}",
            result={
                "status": "error",
                "mode": mode,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=5),
            },
        )
        return

    if isinstance(result, dict) and str(result.get("status", "")).lower() == "success":
        _update_job(
            job_id,
            status="success",
            finished_at=_now_ts(),
            error=None,
            result=result,
        )
        return

    error_message = (
        str(result.get("error", "")).strip()
        if isinstance(result, dict)
        else "Pipeline completed with an unexpected non-success response."
    ) or "Pipeline completed with errors."
    _update_job(
        job_id,
        status="error",
        finished_at=_now_ts(),
        error=error_message,
        result=result if isinstance(result, dict) else {"status": "error", "error": error_message},
    )


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


def _friendly_elevenlabs_http_error(response: requests.Response) -> str:
    raw_text = (response.text or "")[:220]
    status_code = response.status_code
    api_status = ""
    api_message = ""
    try:
        payload = response.json() or {}
        detail = payload.get("detail", {})
        if isinstance(detail, dict):
            api_status = str(detail.get("status", "")).strip().lower()
            api_message = str(detail.get("message", "")).strip()
        elif isinstance(detail, str):
            api_message = detail.strip()
    except Exception:  # pylint: disable=broad-except
        pass

    combined = f"{api_status} {api_message}".lower()
    if api_status == "quota_exceeded" or "quota" in combined:
        return "ElevenLabs quota exceeded. You have no credits left for this request."
    if api_status in {"invalid_api_key", "unauthorized"} or status_code == 401:
        return "Invalid ElevenLabs API key."
    if "voice" in combined:
        return "Voice ID not found or not available for your plan."
    if "model" in combined:
        return "Selected model is not available for your plan."
    if status_code == 429:
        return "ElevenLabs rate limit reached. Please retry shortly."
    return f"ElevenLabs request failed ({status_code}): {api_message or raw_text}"


@web.get("/")
def index():
    if _frontend_index_exists():
        return send_from_directory(FRONTEND_DIST_DIR, "index.html")
    return render_template("index.html")


@web.get("/api/languages")
def languages():
    return jsonify(
        {
            "status": "success",
            "automatic_source_detection": True,
            "languages": language_catalog(),
        }
    )


@web.post("/api/upload")
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


@web.post("/api/preview")
@require_auth
def preview():
    payload = request.get_json(silent=True) or {}
    source_path = payload.get("source_path", "")
    if not str(source_path).strip():
        return jsonify({"status": "error", "error": "source_path is required."}), 400
    book_title = payload.get("book_title")
    openai_api_key = str(payload.get("openai_api_key", "")).strip()
    if not openai_api_key:
        return jsonify({"status": "error", "error": "openai_api_key is required."}), 400
    source_path = str(source_path).strip()

    try:
        source_language = normalize_language_code(payload.get("source_language", "sr"), allow_auto=True)
        target_language = normalize_language_code(payload.get("target_language", "en"))
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400

    job_id = _create_job(
        mode="preview",
        source_path=source_path,
        book_title=book_title,
        source_language=source_language,
        target_language=target_language,
    )
    worker = threading.Thread(
        target=_run_pipeline_job,
        kwargs={
            "job_id": job_id,
            "mode": "preview",
            "source_path": source_path,
            "book_title": book_title,
            "openai_api_key": openai_api_key,
            "skip_transcription": False,
            "source_language": source_language,
            "target_language": target_language,
        },
        daemon=True,
        name=f"pipeline-preview-{job_id[:8]}",
    )
    worker.start()
    return (
        jsonify(
            {
                "status": "queued",
                "mode": "preview",
                "job_id": job_id,
                "message": "Preview job started in background.",
            }
        ),
        202,
    )


@web.post("/api/full")
@require_auth
def full_book():
    payload = request.get_json(silent=True) or {}
    source_path = payload.get("source_path", "")
    if not str(source_path).strip():
        return jsonify({"status": "error", "error": "source_path is required."}), 400
    book_title = payload.get("book_title")
    skip_transcription = bool(payload.get("skip_transcription", False))
    openai_api_key = str(payload.get("openai_api_key", "")).strip()
    if not openai_api_key:
        return jsonify({"status": "error", "error": "openai_api_key is required."}), 400
    source_path = str(source_path).strip()

    try:
        source_language = normalize_language_code(payload.get("source_language", "sr"), allow_auto=True)
        target_language = normalize_language_code(payload.get("target_language", "en"))
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400

    job_id = _create_job(
        mode="full",
        source_path=source_path,
        book_title=book_title,
        source_language=source_language,
        target_language=target_language,
    )
    worker = threading.Thread(
        target=_run_pipeline_job,
        kwargs={
            "job_id": job_id,
            "mode": "full",
            "source_path": source_path,
            "book_title": book_title,
            "openai_api_key": openai_api_key,
            "skip_transcription": skip_transcription,
            "source_language": source_language,
            "target_language": target_language,
        },
        daemon=True,
        name=f"pipeline-full-{job_id[:8]}",
    )
    worker.start()
    return (
        jsonify(
            {
                "status": "queued",
                "mode": "full",
                "job_id": job_id,
                "message": "Full translation job started in background.",
            }
        ),
        202,
    )


@web.get("/api/jobs/<job_id>")
@require_auth
def pipeline_job_status(job_id: str):
    snapshot = _get_job_snapshot(str(job_id).strip())
    if not snapshot:
        return jsonify({"status": "error", "error": "job not found"}), 404
    return jsonify(snapshot)


@web.post("/api/save-translated")
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


@web.post("/api/read")
@require_auth
def read_translation():
    payload = request.get_json(silent=True) or {}
    translated_path = payload.get("translated_path")
    book_title = payload.get("book_title")
    speech_rate = payload.get("speech_rate")
    provider = str(payload.get("provider", "local")).strip().lower() or "local"
    elevenlabs_api_key = payload.get("elevenlabs_api_key")
    elevenlabs_voice_id = payload.get("elevenlabs_voice_id")
    elevenlabs_model_id = payload.get("elevenlabs_model_id")

    try:
        resolved_translated_path = _resolve_translated_artifact_path(translated_path)
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400

    if not resolved_translated_path.exists():
        return jsonify({"status": "error", "error": "Translated artifact does not exist on disk."}), 404

    normalized_rate = None
    if speech_rate is not None:
        try:
            normalized_rate = int(speech_rate)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "error": "speech_rate must be an integer."}), 400

    try:
        if provider == "elevenlabs":
            readback_path = synthesize_translation_readback_elevenlabs(
                translated_path=resolved_translated_path,
                explicit_book_title=str(book_title).strip() if book_title else None,
                api_key=str(elevenlabs_api_key or "").strip() or None,
                voice_id=str(elevenlabs_voice_id or "").strip() or None,
                model_id=str(elevenlabs_model_id or "").strip() or None,
            )
        else:
            readback_path = synthesize_translation_readback(
                translated_path=resolved_translated_path,
                explicit_book_title=str(book_title).strip() if book_title else None,
                speech_rate=normalized_rate,
            )
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"status": "error", "error": str(exc)}), 500

    resolved_readback_path = readback_path if readback_path.is_absolute() else (BASE_DIR / readback_path).resolve()

    return jsonify(
        {
            "status": "success",
            "provider": provider,
            "readback_path": str(resolved_readback_path.relative_to(BASE_DIR.resolve())).replace("\\", "/"),
            "created_at": int(time.time()),
        }
    )


@web.post("/api/elevenlabs/voices")
@require_auth
def list_elevenlabs_voices():
    payload = request.get_json(silent=True) or {}
    api_key = str(payload.get("elevenlabs_api_key", "")).strip()
    if not api_key:
        return jsonify({"status": "error", "error": "elevenlabs_api_key is required."}), 400

    headers = {"xi-api-key": api_key}
    try:
        response = requests.get("https://api.elevenlabs.io/v1/voices", headers=headers, timeout=60)
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"status": "error", "error": f"Failed to reach ElevenLabs: {exc}"}), 502

    if response.status_code != 200:
        return (
            jsonify(
                {
                    "status": "error",
                    "error": _friendly_elevenlabs_http_error(response),
                }
            ),
            502,
        )

    raw_voices = (response.json() or {}).get("voices", [])
    voices = [
        {
            "voice_id": str(item.get("voice_id", "")),
            "name": str(item.get("name", "Unnamed Voice")),
            "category": str(item.get("category", "unknown")),
            "description": str(item.get("description", "")),
        }
        for item in raw_voices
        if item.get("voice_id")
    ]
    free_like_categories = {"premade", "generated"}
    free_voices = [item for item in voices if item.get("category", "").lower() in free_like_categories]
    return jsonify(
        {
            "status": "success",
            "voices": voices,
            "free_voices": free_voices,
            "total_voices": len(voices),
            "free_voice_count": len(free_voices),
        }
    )


@web.get("/health")
def health():
    return jsonify({"status": "ok"})


@web.get("/assets/<path:asset_path>")
def frontend_bundled_assets(asset_path: str):
    if not _frontend_index_exists():
        return jsonify({"status": "error", "error": "Frontend build not found. Run npm run build."}), 404

    asset_root = FRONTEND_DIST_DIR / "assets"
    candidate = (asset_root / asset_path).resolve()
    if candidate.exists() and candidate.is_file() and asset_root.resolve() in candidate.parents:
        return send_from_directory(asset_root, asset_path)
    return jsonify({"status": "error", "error": "Asset not found."}), 404


@web.get("/media/<path:file_path>")
@require_auth
def media(file_path: str):
    requested = (BASE_DIR / file_path).resolve()
    if not requested.exists() or not requested.is_file():
        return jsonify({"status": "error", "error": "File not found."}), 404
    if not _is_within_allowed_media_roots(requested):
        return jsonify({"status": "error", "error": "Access denied for this path."}), 403
    return send_from_directory(requested.parent, requested.name)


@web.get("/<path:path>")
def frontend_assets(path: str):
    if not _frontend_index_exists():
        return jsonify({"status": "error", "error": "Frontend build not found. Run npm run build."}), 404

    candidate = FRONTEND_DIST_DIR / path
    if candidate.exists() and candidate.is_file():
        return send_from_directory(FRONTEND_DIST_DIR, path)
    return send_from_directory(FRONTEND_DIST_DIR, "index.html")


def create_app(test_config: dict | None = None) -> Flask:
    """Create the Flask application for web, worker, and test processes."""
    created_app = Flask(
        __name__,
        instance_path=str(BASE_DIR / "instance"),
        instance_relative_config=True,
    )
    database_url = os.getenv("DATABASE_URL", "sqlite:///audiobook_saas.db").strip()
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://") :]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]

    app_env = os.getenv("APP_ENV", "development").strip().lower()
    created_app.config.from_mapping(
        SECRET_KEY="development-only-secret",
        MAX_CONTENT_LENGTH=2 * 1024 * 1024 * 1024,
        JSON_SORT_KEYS=False,
        ENV=app_env,
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # Migrations are authoritative. Tests may opt into create_all for isolated DBs.
        AUTO_CREATE_DB=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=app_env == "production",
        PERMANENT_SESSION_LIFETIME=30 * 24 * 60 * 60,
        STORAGE_BACKEND=os.getenv("STORAGE_BACKEND", "local"),
        STORAGE_LOCAL_ROOT=os.getenv("STORAGE_LOCAL_ROOT", "instance/storage"),
        S3_ENDPOINT_URL=os.getenv("S3_ENDPOINT_URL", ""),
        S3_REGION=os.getenv("S3_REGION", "auto"),
        S3_BUCKET=os.getenv("S3_BUCKET", ""),
        S3_ACCESS_KEY_ID=os.getenv("S3_ACCESS_KEY_ID", ""),
        S3_SECRET_ACCESS_KEY=os.getenv("S3_SECRET_ACCESS_KEY", ""),
        JOB_EXECUTION_MODE=os.getenv("JOB_EXECUTION_MODE", "thread"),
        REDIS_URL=os.getenv("REDIS_URL", ""),
        ALLOW_BASIC_AUTH=os.getenv("ALLOW_BASIC_AUTH", "true").strip().lower() in {"1", "true", "yes"},
        RATELIMIT_STORAGE_URI=(
            os.getenv("RATELIMIT_STORAGE_URI", "").strip()
            or os.getenv("REDIS_URL", "").strip()
            or "memory://"
        ),
        RATELIMIT_HEADERS_ENABLED=True,
        BASE_URL=os.getenv("APP_BASE_URL", "http://127.0.0.1:8080"),
        FREE_CREDITS=int(os.getenv("FREE_CREDITS", "15")),
        LEMONSQUEEZY_API_KEY=os.getenv("LEMONSQUEEZY_API_KEY", ""),
        LEMONSQUEEZY_STORE_ID=os.getenv("LEMONSQUEEZY_STORE_ID", ""),
        LEMONSQUEEZY_WEBHOOK_SECRET=os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", ""),
        LEMONSQUEEZY_CREATOR_VARIANT_ID=os.getenv("LEMONSQUEEZY_CREATOR_VARIANT_ID", ""),
        LEMONSQUEEZY_STUDIO_VARIANT_ID=os.getenv("LEMONSQUEEZY_STUDIO_VARIANT_ID", ""),
    )
    created_app.config.from_prefixed_env(prefix="APP")
    if test_config:
        created_app.config.update(test_config)
    if created_app.config.get("TESTING"):
        created_app.config["RATELIMIT_ENABLED"] = False

    Path(created_app.instance_path).mkdir(parents=True, exist_ok=True)
    init_extensions(created_app)
    created_app.register_blueprint(web)
    created_app.register_blueprint(auth_api)
    created_app.register_blueprint(billing_api)
    created_app.register_blueprint(projects_api)

    @created_app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=(), payment=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; "
            "connect-src 'self'; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "frame-ancestors 'none'; "
            "img-src 'self' data:; "
            "object-src 'none'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        )
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if str(created_app.config.get("ENV", "development")).lower() == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    _validate_production_config(created_app)
    return created_app


def _validate_production_config(created_app: Flask) -> None:
    """Reject unsafe default secrets when the service runs in production."""
    app_env = str(created_app.config.get("ENV", "development")).strip().lower()
    if app_env != "production" or created_app.config.get("TESTING"):
        return

    secret_key = str(created_app.config.get("SECRET_KEY", "")).strip()
    failures: list[str] = []
    if len(secret_key) < 32 or secret_key == "development-only-secret":
        failures.append("APP_SECRET_KEY must contain at least 32 characters")
    if str(created_app.config.get("SQLALCHEMY_DATABASE_URI", "")).startswith("sqlite"):
        failures.append("DATABASE_URL must use PostgreSQL")
    if str(created_app.config.get("JOB_EXECUTION_MODE", "")).lower() != "rq":
        failures.append("JOB_EXECUTION_MODE must be rq")
    if not str(created_app.config.get("REDIS_URL", "")).strip():
        failures.append("REDIS_URL is required")
    if str(created_app.config.get("STORAGE_BACKEND", "")).lower() != "s3":
        failures.append("STORAGE_BACKEND must be s3")
    for config_key in ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        if not str(created_app.config.get(config_key, "")).strip():
            failures.append(f"{config_key} is required")
    if not str(created_app.config.get("BASE_URL", "")).startswith("https://"):
        failures.append("APP_BASE_URL must be an https:// URL")
    if created_app.config.get("ALLOW_BASIC_AUTH", False):
        failures.append("ALLOW_BASIC_AUTH must be false")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        failures.append("OPENAI_API_KEY is required")
    for config_key in (
        "LEMONSQUEEZY_API_KEY",
        "LEMONSQUEEZY_STORE_ID",
        "LEMONSQUEEZY_WEBHOOK_SECRET",
        "LEMONSQUEEZY_CREATOR_VARIANT_ID",
        "LEMONSQUEEZY_STUDIO_VARIANT_ID",
    ):
        if not str(created_app.config.get(config_key, "")).strip():
            failures.append(f"{config_key} is required")
    if failures:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(failures) + ".")


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
