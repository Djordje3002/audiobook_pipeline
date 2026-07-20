"""Shared Flask extensions."""

from __future__ import annotations

from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def init_extensions(app) -> None:
    """Attach database and migration services to an application instance."""
    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    limiter.init_app(app)

    if app.config.get("AUTO_CREATE_DB", False):
        with app.app_context():
            db.create_all()
