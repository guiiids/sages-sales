import os

from flask import Flask, g, session

from .routes.admin.admin_main_routes import admin_bp
from .routes.api_routes import api_bp
from .routes.main_routes import main_bp
from .utils.auth_util import get_azure_user_info, save_user_to_db, is_user_in_DB


def create_app():
    app = Flask(__name__)

    # Disable JSON key sorting to preserve order
    app.json.sort_keys = False

    # # Set secret key from environment variable
    # app.secret_key = os.getenv("FLASK_SECRET_KEY")
    # if not app.secret_key:
    #     raise ValueError("No FLASK_SECRET_KEY set for Flask application")

    # Alternative: Use app.config for better standardization
    app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY")

    @app.before_request
    def load_user():
        if "user_info" not in session:
            session["user_info"] = get_azure_user_info()
        #To handle the case where user session exists but user is not in DB (e.g. first time login), we check if user is in DB and if not, we save to DB
        elif not is_user_in_DB(session["user_info"]):
            session["user_info"] = save_user_to_db(session["user_info"])
        g.user_info = session["user_info"]

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Remove scoped session at end of each request to prevent stale state."""
        from app.Connection import get_connection
        try:
            conn = get_connection()
            conn.remove_session()
        except Exception:
            pass

    # Register routers (Blueprints)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    app.register_blueprint(admin_bp, url_prefix="/admin")
    # You can add prefixes: app.register_blueprint(api_bp, url_prefix='/api')

    return app
