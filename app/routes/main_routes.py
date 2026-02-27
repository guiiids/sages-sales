#app/routes/main_routes.py

#=====================================================================================================#
#Copyright (c) 2026 Agilent Technologies All rights reserved worldwide.
#Agilent Confidential, Use is permitted only in accordance with applicable End User License Agreement.
#=====================================================================================================#

import logging
import os
import sys

from flask import Blueprint, session, render_template, jsonify, g

from app.Connection import get_connection
from app.utils.admin_auth import is_admin
from app.utils.app_util import full_health_check
from app.utils.sage_custom_log_handler import SageCustomLogHandler

# Configure logging: file, stream, and rotating JSON usage/error handlers
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger(__name__)
logger.setLevel(log_level)
# Clear any existing handlers
if logger.handlers:
    logger.handlers.clear()
# Add file handler with absolute path
os.makedirs('logs', exist_ok=True)
file_handler = logging.FileHandler('logs/app.log')
file_handler.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

if os.getenv("FLASK_ENV", "production") == "development":
    log_level = logging.DEBUG
    logger.setLevel(log_level)
    # Stream logs to stdout for visibility
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

# Configure SageCustomLogHandler
logs_interval_seconds = int(os.getenv("LOGS_NOTIFICATION_INTERVAL_SECONDS", "21600"))  # Default to 6 hours
# Add Teams log handler for ERROR level logs
sage_custom_log_handler = SageCustomLogHandler(logging.ERROR, interval_seconds=logs_interval_seconds)
logger.addHandler(sage_custom_log_handler)

# ============================================================================
# MAIN ROUTES BLUEPRINT
# ============================================================================
main_bp = Blueprint('main', __name__)

file_executed = os.path.abspath(__file__)
sas_token = os.getenv("SAS_TOKEN", "")
# HTML template with Tailwind CSS
MARKED_JS_CDN = "https://cdn.jsdelivr.net/npm/marked/marked.min.js"


@main_bp.route('/')
def index():
    """Serve the chat UI and ensure a session_id is set."""
    logger.info("Index page accessed")
    # Generate a session ID if one doesn't exist
    if 'session_id' not in session:
        session['session_id'] = os.urandom(16).hex()
        logger.info(f"New session created: {session['session_id']}")

    # Check if experimental toggle should be visible
    show_experimental_toggle = os.getenv('ENABLE_EXPERIMENTAL_MODE_TOGGLE', 'false').lower() == 'true'

    # Check if streaming is enabled
    enable_streaming = False#os.getenv('ENABLE_STREAMING', 'false').lower() == 'true'

    user_info = g.user_info
    user_email = user_info.get("email")

    return render_template('index.html',
                           file_executed=file_executed,
                           sas_token=sas_token,
                           marked_js_cdn=MARKED_JS_CDN,
                           show_experimental_toggle=show_experimental_toggle,
                           enable_streaming=enable_streaming,
                           current_user_is_admin=is_admin(user_email)
                           )

@main_bp.route("/health", methods=["GET"])
def health_check():
    """
    Health check endpoint running all checks in parallel.
    """
    overall_status, response = full_health_check()
    return jsonify(response), 200 if overall_status == "green" else 503

@main_bp.route("/healthz", methods=["GET"])
def health_checkz():
    """Health check endpoint for Azure App Service"""
    return jsonify({"status": "healthy"}), 200


@main_bp.route("/evaluation-analysis", methods=["GET"])
def evaluation_analysis():
    """Serve the RADAR and Groundedness Checker Analysis page."""
    try:
        connection = get_connection()
        # Fetch groundedness evaluations
        groundedness_evals = connection.get_groundedness_evaluations(limit=100)

        # Fetch RADAR evaluations from rag_queries.features_json
        radar_evals = connection.get_radar_evaluations(limit=100)

        return render_template('evaluation_analysis.html',
                               groundedness_evaluations=groundedness_evals,
                               groundedness_count=len(groundedness_evals),
                               radar_evaluations=radar_evals,
                               radar_count=len(radar_evals)
                               )

    except Exception as e:
        logger.error(f"Error serving evaluation analysis page: {e}")
        return f"<h1>Error</h1><p>{str(e)}</p>", 500
