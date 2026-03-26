# app/__init__.py
#
# Flask application factory.
# Called by: flask run, gunicorn, and tests.
# Returns a configured Flask app with Oracle connection pool attached.

import os
import oracledb
from flask import Flask
from dotenv import load_dotenv

# Load .env before anything else reads os.environ
load_dotenv()


def create_app() -> Flask:
    """
    Create and configure the Flask application.

    Why a factory function instead of a module-level app object?
    Because tests can call create_app() multiple times with different
    configs without one test's state bleeding into another.
    """
    app = Flask(__name__, template_folder="templates")

    app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]

    # ── Oracle connection pool ─────────────────────────────────
    # Why a pool and not a single connection?
    # A single connection is not thread-safe under Flask's development
    # server, and it breaks completely under any multi-threaded
    # production server like Gunicorn. A pool manages N connections
    # and hands one to each request thread safely.
    #
    # POOL_MIN=2 means 2 connections are always open (warm).
    # POOL_MAX=10 means never more than 10 simultaneous connections.
    # This protects Oracle from being overwhelmed.
    pool = oracledb.create_pool(
        user     = os.environ["ORACLE_USER"],
        password = os.environ["ORACLE_PASSWORD"],
        dsn      = os.environ["ORACLE_DSN"],
        min      = int(os.environ.get("ORACLE_POOL_MIN", 2)),
        max      = int(os.environ.get("ORACLE_POOL_MAX", 10)),
        increment= 1,
    )

    # Attach pool to the app object so every module can reach it
    # via current_app.pool — no global variables needed
    app.pool = pool

    # ── Register blueprints ────────────────────────────────────
    # Blueprints are Flask's way of organising routes into modules.
    # We import here (inside the factory) to avoid circular imports.
    from app.routes import main
    app.register_blueprint(main)

    return app