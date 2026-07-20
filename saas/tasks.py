"""Persistent execution for every creator-selected transformation workflow."""

from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path

from flask import current_app
from pydub import AudioSegment
from redis import Redis
from rq import Queue

from config import OUTPUT_AUDIO_DIR, OUTPUT_TRANSLATED_DIR, PREVIEW_MINUTES, TEMP_CHUNKS_DIR
from main import run_full_book, run_preview
from modules.audio_ingestion import group_segments, save_transcript, transcribe_audio
from modules.document_ingestion import extract_document_text, segment_document
from modules.reader import synthesize_translation_readback_elevenlabs
from modules.translation import extract_glossary, save_glossary, translate_all_segments
from saas.billing import release_job_credits
from saas.extensions import db
from saas.models import Artifact, PipelineJob, utc_now
from saas.storage import get_storage
from saas.workflows import get_workflow


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
    content_type: str = "application/json",
    metadata: dict | None = None,
) -> Artifact:
    stored = storage.save_file(
        path,
        prefix=(
            f"organizations/{job.project.organization_id}/projects/{job.project_id}/"
            f"jobs/{job.id}/{language}"
        ),
        content_type=content_type,
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
        artifact_metadata={"workflow_type": job.project.workflow_type, **(metadata or {})},
    )
    db.session.add(artifact)
    db.session.flush()
    return artifact


def _cleanup_generated_files(paths: set[str]) -> None:
    """Remove only job-generated files from known ephemeral pipeline roots."""
    allowed_roots = (
        Path(OUTPUT_TRANSLATED_DIR).resolve(),
        Path(OUTPUT_AUDIO_DIR).resolve(),
        Path(TEMP_CHUNKS_DIR).resolve(),
    )
    for raw_path in paths:
        candidate = Path(raw_path).resolve()
        if any(root == candidate or root in candidate.parents for root in allowed_roots):
            candidate.unlink(missing_ok=True)


def _preview_audio(source_path: str, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio = AudioSegment.from_file(source_path)
    audio[: PREVIEW_MINUTES * 60 * 1000].export(output_path, format="mp3", bitrate="192k")
    return str(output_path)


def _preview_segments(segments: list[dict]) -> list[dict]:
    limit_seconds = PREVIEW_MINUTES * 60
    selected = [segment for segment in segments if float(segment.get("start", 0)) < limit_seconds]
    return selected or segments[:1]


def _voice_options() -> dict:
    return {
        "api_key": str(current_app.config.get("ELEVENLABS_API_KEY", "")).strip(),
        "voice_id": str(current_app.config.get("ELEVENLABS_VOICE_ID", "")).strip(),
        "model_id": str(current_app.config.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")).strip(),
    }


def _execute_audio_localization(
    *,
    job: PipelineJob,
    source_path: str,
    storage,
    generated_paths: set[str],
    include_audio: bool,
) -> dict:
    targets = list(job.project.target_languages or [])
    target_results: dict[str, dict] = {}
    transcript_artifact_id: str | None = None
    job_key = f"{job.project.slug}-{job.id[:12]}"
    if job.mode == "preview":
        generated_paths.add(str(Path(TEMP_CHUNKS_DIR) / f"{job_key}_preview_source.mp3"))

    for index, target_language in enumerate(targets):
        options = {
            "book_title": job_key,
            "skip_transcription": index > 0,
            "source_language": job.project.source_language,
            "target_language": target_language,
            "safety_identifier": f"saas-{job.requested_by_user_id}",
        }
        result = run_preview(source_path, **options) if job.mode == "preview" else run_full_book(source_path, **options)
        if not isinstance(result, dict) or str(result.get("status", "")).lower() != "success":
            error = result.get("error", "Localization pipeline failed.") if isinstance(result, dict) else "Localization pipeline returned an invalid result."
            raise RuntimeError(str(error))

        generated_paths.update(
            str(result[key])
            for key in ("transcript_path", "glossary_path", "translated_path")
            if result.get(key)
        )
        artifacts: dict[str, str] = {}
        if transcript_artifact_id is None:
            transcript = _persist_result_artifact(
                storage=storage,
                job=job,
                kind="transcript",
                path=result["transcript_path"],
                language=job.project.source_language,
            )
            transcript_artifact_id = transcript.id
        artifacts["transcript"] = transcript_artifact_id

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
        artifacts.update({"glossary": glossary.id, "translation": translation.id})

        voice_stage = "not_requested"
        if include_audio:
            voice_options = _voice_options()
            audio_path = synthesize_translation_readback_elevenlabs(
                translated_path=Path(result["translated_path"]),
                explicit_book_title=f"{job_key}-{target_language}",
                **voice_options,
            )
            generated_paths.add(str(audio_path))
            audio = _persist_result_artifact(
                storage=storage,
                job=job,
                kind="audio",
                path=str(audio_path),
                language=target_language,
                content_type="audio/mpeg",
                metadata={"provider": "elevenlabs", "model_id": voice_options["model_id"], "ai_generated": True},
            )
            artifacts["audio"] = audio.id
            voice_stage = "complete"

        target_results[target_language] = {
            "translated_segments_count": result["translated_segments_count"],
            "voice_stage": voice_stage,
            "cost_estimate": result["cost_estimate"],
            "artifacts": artifacts,
        }
        progress = 15 + round(((index + 1) / max(1, len(targets))) * 80)
        _set_job(
            job,
            stage=f"completed {target_language}",
            progress_percent=progress,
            result={"targets": target_results},
        )
    return {"targets": target_results}


def _execute_audio_transcription(
    *,
    job: PipelineJob,
    source_path: str,
    storage,
    generated_paths: set[str],
) -> dict:
    job_key = f"{job.project.slug}-{job.id[:12]}"
    processing_source = source_path
    if job.mode == "preview":
        preview_path = Path(TEMP_CHUNKS_DIR) / f"{job_key}_transcription_preview.mp3"
        processing_source = _preview_audio(source_path, preview_path)
        generated_paths.add(processing_source)

    _set_job(job, stage="transcribing recording", progress_percent=25)
    raw_segments = transcribe_audio(processing_source, source_language=job.project.source_language)
    segments = group_segments(raw_segments)
    if not segments:
        raise RuntimeError("No transcript segments were generated.")
    transcript_path = save_transcript(segments, f"{job_key}_{job.project.source_language}")
    generated_paths.add(transcript_path)
    artifact = _persist_result_artifact(
        storage=storage,
        job=job,
        kind="transcript",
        path=transcript_path,
        language=job.project.source_language,
    )
    return {"segments_count": len(segments), "artifacts": {"transcript": artifact.id}}


def _document_segments(job: PipelineJob, source_path: str) -> list[dict]:
    segments = segment_document(extract_document_text(source_path))
    if job.mode == "preview":
        return _preview_segments(segments)
    return segments


def _execute_document_translation(
    *,
    job: PipelineJob,
    source_path: str,
    storage,
    generated_paths: set[str],
) -> dict:
    segments = _document_segments(job, source_path)
    if not segments:
        raise RuntimeError("No readable manuscript segments were generated.")
    job_key = f"{job.project.slug}-{job.id[:12]}"
    transcript_path = save_transcript(segments, f"{job_key}_{job.project.source_language}")
    generated_paths.add(transcript_path)
    transcript = _persist_result_artifact(
        storage=storage,
        job=job,
        kind="source_text",
        path=transcript_path,
        language=job.project.source_language,
    )

    targets = list(job.project.target_languages or [])
    target_results: dict[str, dict] = {}
    glossary = extract_glossary(segments)
    for index, target_language in enumerate(targets):
        translation_key = f"{job_key}_{job.project.source_language}_to_{target_language}"
        glossary_path = save_glossary(glossary, translation_key)
        translated_segments = translate_all_segments(
            segments,
            translation_key,
            glossary=glossary,
            source_language=job.project.source_language,
            target_language=target_language,
            safety_identifier=f"saas-{job.requested_by_user_id}",
        )
        translated_path = str(Path(OUTPUT_TRANSLATED_DIR) / f"{translation_key}_translated.json")
        generated_paths.update({glossary_path, translated_path})
        glossary_artifact = _persist_result_artifact(
            storage=storage,
            job=job,
            kind="glossary",
            path=glossary_path,
            language=target_language,
        )
        translation_artifact = _persist_result_artifact(
            storage=storage,
            job=job,
            kind="translation",
            path=translated_path,
            language=target_language,
        )
        target_results[target_language] = {
            "translated_segments_count": len(translated_segments),
            "artifacts": {
                "source_text": transcript.id,
                "glossary": glossary_artifact.id,
                "translation": translation_artifact.id,
            },
        }
        _set_job(
            job,
            stage=f"completed {target_language}",
            progress_percent=20 + round(((index + 1) / max(1, len(targets))) * 75),
            result={"targets": target_results},
        )
    return {"targets": target_results}


def _execute_document_narration(
    *,
    job: PipelineJob,
    source_path: str,
    storage,
    generated_paths: set[str],
) -> dict:
    segments = _document_segments(job, source_path)
    if not segments:
        raise RuntimeError("No readable manuscript segments were generated.")
    job_key = f"{job.project.slug}-{job.id[:12]}"
    narration_segments = [{**segment, "translated_text": segment["original_text"]} for segment in segments]
    source_text_path = Path(OUTPUT_TRANSLATED_DIR) / f"{job_key}_narration_translated.json"
    source_text_path.parent.mkdir(parents=True, exist_ok=True)
    source_text_path.write_text(json.dumps(narration_segments, ensure_ascii=False, indent=2), encoding="utf-8")
    generated_paths.add(str(source_text_path))
    source_text = _persist_result_artifact(
        storage=storage,
        job=job,
        kind="source_text",
        path=str(source_text_path),
        language=job.project.source_language,
    )

    _set_job(job, stage="narrating manuscript", progress_percent=45)
    voice_options = _voice_options()
    audio_path = synthesize_translation_readback_elevenlabs(
        translated_path=source_text_path,
        explicit_book_title=job_key,
        **voice_options,
    )
    generated_paths.add(str(audio_path))
    audio = _persist_result_artifact(
        storage=storage,
        job=job,
        kind="audio",
        path=str(audio_path),
        language=job.project.source_language,
        content_type="audio/mpeg",
        metadata={"provider": "elevenlabs", "model_id": voice_options["model_id"], "ai_generated": True},
    )
    return {
        "segments_count": len(segments),
        "artifacts": {"source_text": source_text.id, "audio": audio.id},
    }


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
            release_job_credits(job, "source missing")
            _set_job(
                job,
                status="error",
                stage="failed",
                progress_percent=100,
                error="Project source is missing.",
                finished_at=utc_now(),
            )
            return

        generated_paths: set[str] = set()
        try:
            storage = get_storage()
            workflow = get_workflow(job.project.workflow_type)
            _set_job(job, stage=f"running {workflow['short_name']}", progress_percent=15)
            with storage.materialize(source.storage_key) as local_source:
                if workflow["id"] == "audio_translate":
                    result = _execute_audio_localization(
                        job=job,
                        source_path=str(local_source),
                        storage=storage,
                        generated_paths=generated_paths,
                        include_audio=False,
                    )
                elif workflow["id"] == "audio_dub":
                    result = _execute_audio_localization(
                        job=job,
                        source_path=str(local_source),
                        storage=storage,
                        generated_paths=generated_paths,
                        include_audio=True,
                    )
                elif workflow["id"] == "audio_transcribe":
                    result = _execute_audio_transcription(
                        job=job,
                        source_path=str(local_source),
                        storage=storage,
                        generated_paths=generated_paths,
                    )
                elif workflow["id"] == "document_translate":
                    result = _execute_document_translation(
                        job=job,
                        source_path=str(local_source),
                        storage=storage,
                        generated_paths=generated_paths,
                    )
                elif workflow["id"] == "document_narrate":
                    result = _execute_document_narration(
                        job=job,
                        source_path=str(local_source),
                        storage=storage,
                        generated_paths=generated_paths,
                    )
                else:  # pragma: no cover - protected by workflow validation
                    raise RuntimeError("Unsupported project workflow.")

            _set_job(
                job,
                status="success",
                stage="complete",
                progress_percent=100,
                error=None,
                result={
                    "status": "success",
                    "mode": job.mode,
                    "workflow_type": workflow["id"],
                    "source_language": job.project.source_language,
                    **result,
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
