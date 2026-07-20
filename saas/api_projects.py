"""Organization-scoped projects, uploads, and persistent processing jobs."""

from __future__ import annotations

import re
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file
from sqlalchemy.exc import IntegrityError

from saas.authn import current_session_user, require_csrf, require_user
from saas.extensions import db
from saas.extensions import limiter
from saas.models import Artifact, Membership, PipelineJob, Project, VoiceConsent, new_id
from saas.storage import get_storage
from saas.tasks import dispatch_pipeline_job
from modules.languages import normalize_language_code
from modules.audio_ingestion import probe_media_duration
from modules.document_ingestion import DOCUMENT_SUFFIXES, estimate_narration_seconds, extract_document_text, manuscript_word_count
from saas.billing import InsufficientCreditsError, release_job_credits, reserve_job_credits
from saas.workflows import get_workflow, workflow_with_availability

projects_api = Blueprint("projects_api", __name__, url_prefix="/api/projects")
ALLOWED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".mp4", ".mov", ".mkv"}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "project"
    return f"{normalized[:220]}-{new_id()[:8]}"


def _membership_for(user_id: str, organization_id: str) -> Membership | None:
    return Membership.query.filter_by(user_id=user_id, organization_id=organization_id).first()


def _project_for_user(project_id: str, user_id: str) -> Project | None:
    project = db.session.get(Project, project_id)
    if not project or not _membership_for(user_id, project.organization_id):
        return None
    return project


def _target_languages(raw_value) -> list[str]:
    values = raw_value if isinstance(raw_value, list) else ([] if raw_value is None else [raw_value])
    normalized: list[str] = []
    for value in values:
        code = normalize_language_code(value)
        if code not in normalized:
            normalized.append(code)
    return normalized[:12]


@projects_api.get("")
@require_user
def list_projects():
    user = current_session_user()
    organization_ids = [
        row.organization_id for row in Membership.query.filter_by(user_id=user.id).all()
    ]
    projects = (
        Project.query.filter(Project.organization_id.in_(organization_ids))
        .order_by(Project.updated_at.desc())
        .all()
        if organization_ids
        else []
    )
    return jsonify({"status": "success", "projects": [project.to_dict() for project in projects]})


@projects_api.post("")
@require_user
@require_csrf
def create_project():
    user = current_session_user()
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()
    organization_id = str(payload.get("organization_id", "")).strip()
    try:
        workflow = get_workflow(payload.get("workflow_type"))
        source_language = normalize_language_code(payload.get("source_language", "auto"), allow_auto=True)
        target_languages = _target_languages(payload.get("target_languages", []))
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400

    if len(title) < 2 or len(title) > 240:
        return jsonify({"status": "error", "error": "Project title must be 2-240 characters."}), 400
    membership = _membership_for(user.id, organization_id)
    if not membership:
        return jsonify({"status": "error", "error": "Organization not found."}), 404
    if workflow["requires_targets"] and not target_languages:
        return jsonify({"status": "error", "error": "Select at least one target language."}), 400
    if workflow["id"] == "document_narrate" and source_language == "auto":
        return jsonify({"status": "error", "error": "Choose the manuscript language for narration."}), 400
    if workflow["requires_targets"] and source_language != "auto" and source_language in target_languages:
        return jsonify({"status": "error", "error": "Source and target languages must be different."}), 400

    rights_confirmed = bool(payload.get("rights_confirmed", False))
    voice_consent_confirmed = bool(payload.get("voice_consent_confirmed", False))
    project = Project(
        organization_id=organization_id,
        created_by_user_id=user.id,
        title=title,
        slug=_slug(title),
        workflow_type=workflow["id"],
        source_language=source_language,
        target_languages=target_languages if workflow["requires_targets"] else [],
        rights_confirmed=rights_confirmed,
        voice_consent_confirmed=voice_consent_confirmed,
    )
    db.session.add(project)
    db.session.flush()
    if voice_consent_confirmed:
        db.session.add(
            VoiceConsent(
                project_id=project.id,
                confirmed_by_user_id=user.id,
                speaker_name=str(payload.get("speaker_name", "Primary narrator")).strip()[:160]
                or "Primary narrator",
                ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=str(request.user_agent)[:512],
            )
        )
    db.session.commit()
    return jsonify({"status": "success", "project": project.to_dict()}), 201


@projects_api.get("/<project_id>")
@require_user
def get_project(project_id: str):
    user = current_session_user()
    project = _project_for_user(project_id, user.id)
    if not project:
        return jsonify({"status": "error", "error": "Project not found."}), 404
    artifacts = Artifact.query.filter_by(project_id=project.id).order_by(Artifact.created_at.desc()).all()
    jobs = PipelineJob.query.filter_by(project_id=project.id).order_by(PipelineJob.created_at.desc()).limit(20).all()
    return jsonify(
        {
            "status": "success",
            "project": project.to_dict(),
            "workflow": workflow_with_availability(project.workflow_type),
            "artifacts": [artifact.to_dict() for artifact in artifacts],
            "jobs": [job.to_dict() for job in jobs],
        }
    )


@projects_api.get("/<project_id>/artifacts/<artifact_id>/download")
@require_user
def download_project_artifact(project_id: str, artifact_id: str):
    user = current_session_user()
    project = _project_for_user(project_id, user.id)
    if not project:
        return jsonify({"status": "error", "error": "Project not found."}), 404
    artifact = Artifact.query.filter_by(id=artifact_id, project_id=project.id).first()
    if not artifact:
        return jsonify({"status": "error", "error": "Artifact not found."}), 404
    if artifact.kind == "source":
        return jsonify({"status": "error", "error": "Source downloads are not available here."}), 403
    with get_storage().materialize(artifact.storage_key) as local_path:
        content = BytesIO(local_path.read_bytes())
    return send_file(
        content,
        mimetype=artifact.content_type or "application/octet-stream",
        as_attachment=True,
        download_name=artifact.original_filename or f"{artifact.kind}.json",
    )


@projects_api.post("/<project_id>/source")
@limiter.limit("20 per hour")
@require_user
@require_csrf
def upload_project_source(project_id: str):
    user = current_session_user()
    project = _project_for_user(project_id, user.id)
    if not project:
        return jsonify({"status": "error", "error": "Project not found."}), 404
    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"status": "error", "error": "Select a source file."}), 400

    workflow = get_workflow(project.workflow_type)
    suffix = re.search(r"(\.[A-Za-z0-9]+)$", uploaded_file.filename)
    normalized_suffix = suffix.group(1).lower() if suffix else ""
    allowed_suffixes = ALLOWED_AUDIO_SUFFIXES if workflow["input_kind"] == "audio" else DOCUMENT_SUFFIXES
    if normalized_suffix not in allowed_suffixes:
        expected = "audio or video" if workflow["input_kind"] == "audio" else "TXT, Markdown, or DOCX manuscript"
        return jsonify({"status": "error", "error": f"Upload a supported {expected} file for this workflow."}), 400

    storage = get_storage()
    stored = storage.save_upload(
        uploaded_file,
        prefix=f"organizations/{project.organization_id}/projects/{project.id}/source",
    )
    artifact_metadata = {"input_kind": workflow["input_kind"], "workflow_type": workflow["id"]}
    try:
        with storage.materialize(stored.key) as local_source:
            if workflow["input_kind"] == "audio":
                project.duration_seconds = probe_media_duration(local_source)
            else:
                document_text = extract_document_text(local_source)
                project.duration_seconds = estimate_narration_seconds(document_text)
                artifact_metadata["word_count"] = manuscript_word_count(document_text)
    except Exception as exc:  # pylint: disable=broad-except
        storage.delete(stored.key)
        return jsonify({"status": "error", "error": str(exc) or "The source file could not be read."}), 400

    artifact = Artifact(
        project_id=project.id,
        kind="source",
        storage_key=stored.key,
        original_filename=stored.original_filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        language=project.source_language,
        artifact_metadata=artifact_metadata,
    )
    project.status = "ready"
    db.session.add(artifact)
    db.session.commit()
    return jsonify({"status": "success", "artifact": artifact.to_dict(), "project": project.to_dict()}), 201


@projects_api.post("/<project_id>/jobs")
@limiter.limit("30 per hour")
@require_user
@require_csrf
def create_project_job(project_id: str):
    user = current_session_user()
    project = _project_for_user(project_id, user.id)
    if not project:
        return jsonify({"status": "error", "error": "Project not found."}), 404
    workflow = workflow_with_availability(project.workflow_type)
    if not project.rights_confirmed:
        return jsonify({"status": "error", "error": "Content rights must be confirmed."}), 409
    if workflow["requires_voice_consent"] and not project.voice_consent_confirmed:
        return jsonify({"status": "error", "error": "Voice consent must be confirmed."}), 409
    if not workflow["available"]:
        return jsonify({"status": "error", "error": workflow["availability_note"]}), 409
    if not Artifact.query.filter_by(project_id=project.id, kind="source").first():
        return jsonify({"status": "error", "error": "Upload the project source before starting a job."}), 409

    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode", "preview")).strip().lower()
    if mode not in {"preview", "full"}:
        return jsonify({"status": "error", "error": "mode must be preview or full."}), 400

    active_job = PipelineJob.query.filter(
        PipelineJob.project_id == project.id,
        PipelineJob.status.in_({"queued", "running", "retrying"}),
    ).first()
    if active_job:
        return (
            jsonify(
                {
                    "status": "error",
                    "error": "This project already has an active production job.",
                    "job": active_job.to_dict(),
                }
            ),
            409,
        )

    idempotency_key = str(request.headers.get("Idempotency-Key", "")).strip() or None
    if idempotency_key:
        existing = PipelineJob.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return jsonify({"status": "success", "job": existing.to_dict()}), 200

    job = PipelineJob(
        project_id=project.id,
        requested_by_user_id=user.id,
        mode=mode,
        idempotency_key=idempotency_key,
    )
    db.session.add(job)
    try:
        db.session.flush()
        reserved_credits = reserve_job_credits(job)
        db.session.commit()
    except InsufficientCreditsError as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "status": "error",
                    "error": str(exc),
                    "required_credits": exc.required,
                    "available_credits": exc.available,
                }
            ),
            402,
        )
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"status": "error", "error": str(exc)}), 409
    except IntegrityError:
        db.session.rollback()
        existing = PipelineJob.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return jsonify({"status": "success", "job": existing.to_dict()}), 200
        raise

    try:
        job.queue_job_id = dispatch_pipeline_job(job.id)
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        job.status = "error"
        job.stage = "dispatch failed"
        job.error = str(exc)
        release_job_credits(job, "dispatch failed")
        db.session.commit()
        return jsonify({"status": "error", "error": str(exc), "job": job.to_dict()}), 503

    return jsonify({"status": "success", "job": job.to_dict(), "reserved_credits": reserved_credits}), 202


@projects_api.get("/<project_id>/jobs/<job_id>")
@require_user
def get_project_job(project_id: str, job_id: str):
    user = current_session_user()
    project = _project_for_user(project_id, user.id)
    if not project:
        return jsonify({"status": "error", "error": "Project not found."}), 404
    job = PipelineJob.query.filter_by(id=job_id, project_id=project.id).first()
    if not job:
        return jsonify({"status": "error", "error": "Job not found."}), 404
    return jsonify({"status": "success", "job": job.to_dict()})
