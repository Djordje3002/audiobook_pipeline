"""Creator-facing transformation workflows and capability requirements."""

from __future__ import annotations

from flask import current_app, has_app_context


WORKFLOWS = (
    {
        "id": "audio_translate",
        "name": "Translate a recording",
        "short_name": "Audio → translated text",
        "description": "Turn spoken audio into timestamped, glossary-controlled editions in other languages.",
        "input_kind": "audio",
        "output_kind": "translated_text",
        "requires_targets": True,
        "requires_voice_provider": False,
        "requires_voice_consent": False,
        "icon": "globe",
    },
    {
        "id": "audio_transcribe",
        "name": "Transcribe a recording",
        "short_name": "Audio → transcript",
        "description": "Create a clean timestamped transcript without translating the recording.",
        "input_kind": "audio",
        "output_kind": "transcript",
        "requires_targets": False,
        "requires_voice_provider": False,
        "requires_voice_consent": False,
        "icon": "wave",
    },
    {
        "id": "audio_dub",
        "name": "Dub into other languages",
        "short_name": "Audio → translated audio",
        "description": "Translate a recording and render narrated audio for every selected language.",
        "input_kind": "audio",
        "output_kind": "translated_audio",
        "requires_targets": True,
        "requires_voice_provider": True,
        "requires_voice_consent": True,
        "icon": "spark",
    },
    {
        "id": "document_translate",
        "name": "Translate a book",
        "short_name": "Book → translated text",
        "description": "Turn a TXT, Markdown, or DOCX manuscript into consistent multilingual editions.",
        "input_kind": "document",
        "output_kind": "translated_text",
        "requires_targets": True,
        "requires_voice_provider": False,
        "requires_voice_consent": False,
        "icon": "file",
    },
    {
        "id": "document_narrate",
        "name": "Create an audiobook",
        "short_name": "Book → narrated audio",
        "description": "Convert a manuscript into a narrated audio edition in its original language.",
        "input_kind": "document",
        "output_kind": "narrated_audio",
        "requires_targets": False,
        "requires_voice_provider": True,
        "requires_voice_consent": True,
        "icon": "play",
    },
)

WORKFLOW_BY_ID = {workflow["id"]: workflow for workflow in WORKFLOWS}


def voice_provider_configured() -> bool:
    if not has_app_context():
        return False
    return bool(
        str(current_app.config.get("ELEVENLABS_API_KEY", "")).strip()
        and str(current_app.config.get("ELEVENLABS_VOICE_ID", "")).strip()
    )


def get_workflow(workflow_id: str | None) -> dict:
    normalized = str(workflow_id or "audio_translate").strip().lower()
    workflow = WORKFLOW_BY_ID.get(normalized)
    if not workflow:
        raise ValueError("Unknown project workflow.")
    return dict(workflow)


def workflow_with_availability(workflow_id: str) -> dict:
    workflow = get_workflow(workflow_id)
    available = not workflow["requires_voice_provider"] or voice_provider_configured()
    return {
        **workflow,
        "available": available,
        "availability_note": "Ready" if available else "Connect a voice provider to run this workflow",
    }


def workflow_catalog() -> list[dict]:
    return [workflow_with_availability(workflow["id"]) for workflow in WORKFLOWS]
