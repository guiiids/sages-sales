import argparse
import logging
import os
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler

from app import create_app
from app.utils import notification_util
from app.utils.app_util import clean_session_in_db, full_health_check
from app.utils.rag_util import rag_assistants_last_access, rag_assistants
from app.utils.sage_custom_log_handler import SageCustomLogHandler

# Configure logging: file, stream, and rotating JSON usage/error handlers
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger()
logger.setLevel(log_level)
# Clear any existing handlers
if logger.handlers:
    logger.handlers.clear()
# Add file handler with absolute path
file_handler = logging.FileHandler('logs/app.log')
file_handler.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

if os.getenv("FLASK_ENV", "production") == "development":
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

app = create_app()

def health_monitor_job():
    try:
        overall_status, response = full_health_check()

        skip_health_notifications = os.getenv("SKIP_HEALTH_NOTIFICATIONS", "false").lower() == "true"
        if skip_health_notifications:
            logger.info("Skipping health notifications as per configuration")
            return
        # Send notification if application health check fails.
        logger.info(f"Sending application health notification")
        payload = notification_util.build_health_check_card_data(response)
        send_email = False
        if overall_status != "green":
            send_email = True
        health_notification = notification_util.NotificationTemplate(payload, is_adaptive_card=True,
                                                                     is_email=send_email, is_teams=True)
        notification_util.send_notification(health_notification)
    except Exception as e:
        logger.error(f"Health monitor error: {e}")


# Session TTL in seconds (2 hours) - sessions inactive longer than this are cleaned up
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", 7200))  # Default: 2 hours


def cleanup_expired_sessions():
    """Remove RAG assistant sessions that have been inactive for longer than SESSION_TTL_SECONDS.

    This prevents memory leaks from abandoned sessions (e.g., users who closed their browser).
    Multi-turn conversations are preserved for active sessions.
    """
    current_time = time.time()
    expired_sessions = []

    for session_id, last_access in list(rag_assistants_last_access.items()):
        if current_time - last_access > SESSION_TTL_SECONDS:
            expired_sessions.append(session_id)

    for session_id in expired_sessions:
        rag_assistants.pop(session_id, None)
        rag_assistants_last_access.pop(session_id, None)
        if session_id:
            clean_session_in_db(session_id)

    if expired_sessions:
        logger.info(
            f"Session cleanup: removed {len(expired_sessions)} expired sessions. Active sessions: {len(rag_assistants)}")

if __name__ == "__main__":

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Run the Flask RAG application')
    # Priority: CLI --port > WEBSITES_PORT > PORT env > 5001 default
    env_default_port = int(os.environ.get("WEBSITES_PORT", os.environ.get("PORT", "5001")))
    parser.add_argument('--port', type=int, default=env_default_port,
                        help=f'Port to run the server on (default: {env_default_port})')
    args = parser.parse_args()

    port = args.port
    logger.info(f"Starting Flask app on port {port}")

    # Read interval from environment variable, default to 30 if not set
    HEALTH_MONITOR_INTERVAL_MINUTES = int(os.getenv("HEALTH_MONITOR_INTERVAL_MINUTES", 30))


    # Start the scheduler when the app starts
    try:
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(health_monitor_job, 'interval', minutes=HEALTH_MONITOR_INTERVAL_MINUTES)
        # Session cleanup job - runs every 15 minutes to remove expired sessions (prevents memory leak)
        scheduler.add_job(cleanup_expired_sessions, 'interval', minutes=15)
        scheduler.start()
        logger.info(f"Scheduler started (health check: {HEALTH_MONITOR_INTERVAL_MINUTES}min, session cleanup: 15min, TTL: {SESSION_TTL_SECONDS}s)")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")

    # Run the app
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
