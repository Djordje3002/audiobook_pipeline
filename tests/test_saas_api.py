"""Account, organization, project, and storage API tests."""

from __future__ import annotations

import io
import wave

from app import create_app


def _wav_bytes(duration_seconds: float = 0.25) -> bytes:
    buffer = io.BytesIO()
    sample_rate = 8000
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * int(sample_rate * duration_seconds))
    return buffer.getvalue()


def _test_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "AUTO_CREATE_DB": True,
            "STORAGE_BACKEND": "local",
            "STORAGE_LOCAL_ROOT": str(tmp_path / "storage"),
            "ELEVENLABS_API_KEY": "",
            "ELEVENLABS_VOICE_ID": "",
        }
    )


def _register(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "creator@example.com",
            "display_name": "Test Creator",
            "password": "long-test-password",
        },
    )
    assert response.status_code == 201
    return response.get_json()


def test_registration_creates_session_and_organization(tmp_path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()
    registered = _register(client)

    assert registered["user"]["email"] == "creator@example.com"
    assert registered["organizations"][0]["role"] == "owner"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["user"]["display_name"] == "Test Creator"


def test_project_creation_and_source_upload(tmp_path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()
    registered = _register(client)
    csrf = registered["csrf_token"]
    organization_id = registered["organizations"][0]["id"]

    created = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "organization_id": organization_id,
            "title": "The Night Train",
            "workflow_type": "audio_translate",
            "source_language": "sr",
            "target_languages": ["en", "de"],
            "rights_confirmed": True,
        },
    )
    assert created.status_code == 201
    project = created.get_json()["project"]
    assert project["target_languages"] == ["en", "de"]

    audio_bytes = _wav_bytes()
    uploaded = client.post(
        f"/api/projects/{project['id']}/source",
        headers={"X-CSRF-Token": csrf},
        data={"file": (io.BytesIO(audio_bytes), "chapter.wav")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    assert uploaded.get_json()["artifact"]["size_bytes"] == len(audio_bytes)

    detail = client.get(f"/api/projects/{project['id']}")
    assert detail.status_code == 200
    assert detail.get_json()["artifacts"][0]["kind"] == "source"
    assert detail.get_json()["workflow"]["short_name"] == "Audio → translated text"


def test_project_jobs_require_content_rights(tmp_path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()
    registered = _register(client)
    csrf = registered["csrf_token"]

    created = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "organization_id": registered["organizations"][0]["id"],
            "title": "Unconfirmed project",
            "workflow_type": "audio_transcribe",
            "target_languages": ["en"],
        },
    )
    project_id = created.get_json()["project"]["id"]

    response = client.post(
        f"/api/projects/{project_id}/jobs",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "preview"},
    )
    assert response.status_code == 409
    assert "rights" in response.get_json()["error"].lower()


def test_workflow_catalog_exposes_creator_choices(tmp_path) -> None:
    client = _test_app(tmp_path).test_client()

    response = client.get("/api/workflows")

    assert response.status_code == 200
    workflows = {item["id"]: item for item in response.get_json()["workflows"]}
    assert set(workflows) == {
        "audio_translate",
        "audio_transcribe",
        "audio_dub",
        "document_translate",
        "document_narrate",
    }
    assert workflows["document_translate"]["input_kind"] == "document"
    assert workflows["audio_dub"]["available"] is False


def test_document_translation_accepts_utf8_manuscript(tmp_path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()
    registered = _register(client)
    csrf = registered["csrf_token"]

    created = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "organization_id": registered["organizations"][0]["id"],
            "title": "Book translation",
            "workflow_type": "document_translate",
            "source_language": "sr",
            "target_languages": ["en", "de"],
            "rights_confirmed": True,
        },
    )
    assert created.status_code == 201
    project = created.get_json()["project"]
    manuscript = ("Ovo je početak jedne duge priče. " * 12).encode("utf-8")

    uploaded = client.post(
        f"/api/projects/{project['id']}/source",
        headers={"X-CSRF-Token": csrf},
        data={"file": (io.BytesIO(manuscript), "manuscript.txt")},
        content_type="multipart/form-data",
    )

    assert uploaded.status_code == 201
    payload = uploaded.get_json()
    assert payload["artifact"]["metadata"]["word_count"] > 20
    assert payload["project"]["duration_seconds"] > 0


def test_audiobook_requires_explicit_manuscript_language(tmp_path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()
    registered = _register(client)

    response = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": registered["csrf_token"]},
        json={
            "organization_id": registered["organizations"][0]["id"],
            "title": "Narrated book",
            "workflow_type": "document_narrate",
            "source_language": "auto",
            "rights_confirmed": True,
            "voice_consent_confirmed": True,
        },
    )

    assert response.status_code == 400
    assert "manuscript language" in response.get_json()["error"].lower()


def test_voice_workflow_is_gated_when_provider_is_missing(tmp_path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()
    registered = _register(client)
    csrf = registered["csrf_token"]
    created = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "organization_id": registered["organizations"][0]["id"],
            "title": "Translated narration",
            "workflow_type": "audio_dub",
            "source_language": "sr",
            "target_languages": ["en"],
            "rights_confirmed": True,
            "voice_consent_confirmed": True,
        },
    ).get_json()["project"]
    client.post(
        f"/api/projects/{created['id']}/source",
        headers={"X-CSRF-Token": csrf},
        data={"file": (io.BytesIO(_wav_bytes()), "chapter.wav")},
        content_type="multipart/form-data",
    )

    response = client.post(
        f"/api/projects/{created['id']}/jobs",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "preview"},
    )

    assert response.status_code == 409
    assert "voice provider" in response.get_json()["error"].lower()


def test_text_workflow_does_not_require_voice_consent(tmp_path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()
    registered = _register(client)
    csrf = registered["csrf_token"]
    created = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "organization_id": registered["organizations"][0]["id"],
            "title": "Text localization",
            "workflow_type": "audio_translate",
            "target_languages": ["en"],
            "rights_confirmed": True,
            "voice_consent_confirmed": False,
        },
    ).get_json()["project"]

    response = client.post(
        f"/api/projects/{created['id']}/jobs",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "preview"},
    )

    assert response.status_code == 409
    assert "source" in response.get_json()["error"].lower()
    assert "voice" not in response.get_json()["error"].lower()
