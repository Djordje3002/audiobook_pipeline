"""HTTP-level smoke tests for the Flask application."""

from __future__ import annotations

import base64

import pytest

from app import create_app


def _basic_auth(username: str = "admin", password: str = "changeme") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _app():
    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "AUTO_CREATE_DB": True,
        }
    )


def test_health_is_public() -> None:
    app = _app()
    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_language_catalog_is_public() -> None:
    app = _app()
    response = app.test_client().get("/api/languages")

    assert response.status_code == 200
    assert len(response.get_json()["languages"]) >= 30


def test_home_is_public() -> None:
    app = _app()
    response = app.test_client().get("/")

    assert response.status_code == 200


def test_home_accepts_development_credentials(monkeypatch) -> None:
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "changeme")
    app = _app()
    response = app.test_client().get("/", headers=_basic_auth())

    assert response.status_code == 200


def test_missing_upload_file_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "changeme")
    app = _app()
    response = app.test_client().post("/api/upload", headers=_basic_auth())

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    assert response.headers["Cache-Control"] == "no-store"


def test_production_rejects_development_topology(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        create_app({"AUTO_CREATE_DB": False})
