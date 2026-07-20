"""Account, organization, project, and storage API tests."""

from __future__ import annotations

import io

from app import create_app


def _test_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "AUTO_CREATE_DB": True,
            "STORAGE_BACKEND": "local",
            "STORAGE_LOCAL_ROOT": str(tmp_path / "storage"),
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
            "source_language": "sr",
            "target_languages": ["en", "de"],
            "rights_confirmed": True,
            "voice_consent_confirmed": True,
            "speaker_name": "Rights holder",
        },
    )
    assert created.status_code == 201
    project = created.get_json()["project"]
    assert project["target_languages"] == ["en", "de"]

    uploaded = client.post(
        f"/api/projects/{project['id']}/source",
        headers={"X-CSRF-Token": csrf},
        data={"file": (io.BytesIO(b"fake-audio"), "chapter.mp3")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    assert uploaded.get_json()["artifact"]["size_bytes"] == len(b"fake-audio")

    detail = client.get(f"/api/projects/{project['id']}")
    assert detail.status_code == 200
    assert detail.get_json()["artifacts"][0]["kind"] == "source"


def test_project_jobs_require_rights_and_voice_consent(tmp_path) -> None:
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
    assert "consent" in response.get_json()["error"].lower()
