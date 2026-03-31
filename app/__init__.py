# app/__init__.py
import os
import oracledb
from flask import Flask
from dotenv import load_dotenv

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]

    # ── Oracle connection pool ─────────────────────────────────
    pool = oracledb.create_pool(
        user     = os.environ["ORACLE_USER"],
        password = os.environ["ORACLE_PASSWORD"],
        dsn      = os.environ["ORACLE_DSN"],
        min      = int(os.environ.get("ORACLE_POOL_MIN", 2)),
        max      = int(os.environ.get("ORACLE_POOL_MAX", 10)),
        increment= 1,
    )
    app.pool = pool

    # ── Auto-discover schema at startup ───────────────────────
    # We push an app context manually here so discover_schema()
    # can call current_app.pool before the first request arrives.
    # Without this, current_app is not available outside a request.
    with app.app_context():
        try:
            from app.rag import discover_schema
            app.schema_cache = discover_schema()
            app.logger.info(
                f"Schema discovery complete: "
                f"{len(app.schema_cache)} tables loaded."
            )
        except Exception as e:
            app.logger.error(f"Schema discovery failed: {e}")
            app.schema_cache = {}

    # ── Register blueprints ────────────────────────────────────
    from app.routes import main
    app.register_blueprint(main)

    return app