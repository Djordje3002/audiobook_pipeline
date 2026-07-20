"""Persistent pipeline execution and Redis/in-process dispatch."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path

from flask import current_app
from redis import Redis
from rq import Queue

from main import run_full_book, run_preview
from config import OUTPUT_TRANSLATED_DIR, TEMP_CHUNKS_DIR
from saas.billing import release_job_credits
from saas.extensions import db
from saas.models import Artifact, PipelineJob, utc_now
from saas.storage import get_storage


def _set_job(job: PipelineJob, **updates) -> None:
    for field, value in updates.items():
        setattr(job, field, value)
    db.session.commit()


def _persist_result_artifact(
    *,
    storage,
    job: PipelineJob,
    kind: str,
    path: str,
    language: str,
) -> Artifact:
    stored = storage.save_file(
        path,
        prefix=(
            f"organizations/{job.project.organization_id}/projects/{job.project_id}/"
            f"jobs/{job.id}/{language}"
        ),
        content_type="application/json",
    )
    artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind=kind,
        storage_key=stored.key,
        original_filename=stored.original_filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        language=language,
    )
    db.session.add(artifact)
    db.session.flush()
    return artifact


def _cleanup_generated_files(paths: set[str]) -> None:
    """Remove only job-generated files from known ephemeral pipeline roots."""
    allowed_roots = (Path(OUTPUT_TRANSLATED_DIR).resolve(), Path(TEMP_CHUNKS_DIR).resolve())
    for raw_path in paths:
        candidate = Path(raw_path).resolve()
        if any(root == candidate or root in candidate.parents for root in allowed_roots):
            candidate.unlink(missing_ok=True)


def execute_pipeline_job(job_id: str) -> None:
    """RQ entrypoint. Importing the application supplies the configured context."""
    from app import app  # pylint: disable=import-outside-toplevel

    _execute_with_app(app, job_id)


def _execute_with_app(app, job_id: str) -> None:
    with app.app_context():
        job = db.session.get(PipelineJob, job_id)
        if not job or job.status not in {"queued", "retrying"}:
            return

        _set_job(job, status="running", stage="preparing source", progress_percent=5, started_at=utc_now())
        source = Artifact.query.filter_by(project_id=job.project_id, kind="source").order_by(Artifact.created_at.desc()).first()
        if not source:
            release_job_credits(job, "source audio missing")
            _set_job(
                job,
                status="error",
                stage="failed",
                progress_percent=100,
                error="Project source audio is missing.",
                finished_at=utc_now(),
            )
            return

        try:
            storage = get_storage()
            _set_job(job, stage="transcribing and translating", progress_percent=15)
            generated_paths: set[str] = set()
            job_artifact_key = f"{job.project.slug}-{job.id[:12]}"
            if job.mode == "preview":
                generated_paths.add(
                    str(Path(TEMP_CHUNKS_DIR) / f"{job_artifact_key}_preview_source.mp3")
                )
            with storage.materialize(source.storage_key) as local_source:
                targets = list(job.project.target_languages or [])
                target_results: dict[str, dict] = {}
                transcript_artifact_id: str | None = None
                safety_identifier = f"saas-{job.requested_by_user_id}"

                for index, target_language in enumerate(targets):
                    common_options = {
                        "book_title": job_artifact_key,
                        "skip_transcription": index > 0,
                        "source_language": job.project.source_language,
                        "target_language": target_language,
                        "safety_identifier": safety_identifier,
                    }
                    if job.mode == "preview":
                        result = run_preview(str(local_source), **common_options)
                    else:
                        result = run_full_book(str(local_source), **common_options)

                    if not isinstance(result, dict) or str(result.get("status", "")).lower() != "success":
                        error = (
                            str(result.get("error", "Pipeline failed."))
                            if isinstance(result, dict)
                            else "Pipeline failed."
                        )
                        _set_job(
                            job,
                            status="error",
                            stage=f"failed for {target_language}",
                            progress_percent=100,
                            error=error,
                            result={"targets": target_results, "failed_target": target_language},
                            finished_at=utc_now(),
                        )
                        release_job_credits(job, f"pipeline failed for {target_language}")
                        db.session.commit()
                        return

                    generated_paths.update(
                        str(result[path_key])
                        for path_key in ("transcript_path", "glossary_path", "translated_path")
                        if result.get(path_key)
                    )

                    artifact_ids: dict[str, str] = {}
                    if transcript_artifact_id is None:
                        transcript = _persist_result_artifact(
                            storage=storage,
                            job=job,
                            kind="transcript",
                            path=result["transcript_path"],
                            language=job.project.source_language,
                        )
                        transcript_artifact_id = transcript.id
                    artifact_ids["transcript"] = transcript_artifact_id

                    glossary = _persist_result_artifact(
                        storage=storage,
                        job=job,
                        kind="glossary",
                        path=result["glossary_path"],
                        language=target_language,
                    )
                    translation = _persist_result_artifact(
                        storage=storage,
                        job=job,
                        kind="translation",
                        path=result["translated_path"],
                        language=target_language,
                    )
                    artifact_ids.update({"glossary": glossary.id, "translation": translation.id})

                    target_results[target_language] = {
                        "translated_segments_count": result["translated_segments_count"],
                        "voice_stage": result["voice_stage"],
                        "cost_estimate": result["cost_estimate"],
                        "artifacts": artifact_ids,
                    }
                    progress = 15 + round(((index + 1) / max(1, len(targets))) * 80)
                    _set_job(
                        job,
                        stage=f"completed {target_language}",
                        progress_percent=progress,
                        result={"targets": target_results},
                    )

            _set_job(
                job,
                status="success",
                stage="complete",
                progress_percent=100,
                error=None,
                result={
                    "status": "success",
                    "mode": job.mode,
                    "source_language": job.project.source_language,
                    "targets": target_results,
                },
                finished_at=utc_now(),
            )
        except Exception as exc:  # pylint: disable=broad-except
            release_job_credits(job, f"{type(exc).__name__}: {exc}")
            _set_job(
                job,
                status="error",
                stage="failed",
                progress_percent=100,
                error=f"{type(exc).__name__}: {exc}",
                result={"traceback": traceback.format_exc(limit=5)},
                finished_at=utc_now(),
            )
        finally:
            if "generated_paths" in locals():
                _cleanup_generated_files(generated_paths)
            db.session.remove()


def dispatch_pipeline_job(job_id: str) -> str:
    """Dispatch through RQ in production, with an explicit local thread fallback."""
    app = current_app._get_current_object()  # pylint: disable=protected-access
    mode = str(app.config.get("JOB_EXECUTION_MODE", "thread")).strip().lower()
    redis_url = str(app.config.get("REDIS_URL", "")).strip()

    if mode == "rq":
        if not redis_url:
            raise RuntimeError("REDIS_URL is required when JOB_EXECUTION_MODE=rq.")
        connection = Redis.from_url(redis_url)
        queue = Queue("pipeline", connection=connection, default_timeout=6 * 60 * 60)
        queued = queue.enqueue(execute_pipeline_job, job_id, job_timeout=6 * 60 * 60, result_ttl=86400)
        return str(queued.id)

    worker = threading.Thread(
        target=_execute_with_app,
        args=(app, job_id),
        daemon=True,
        name=f"saas-pipeline-{job_id[:8]}",
    )
    worker.start()
    return f"thread:{worker.name}"
