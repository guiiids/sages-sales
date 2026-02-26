"""
Gunicorn configuration file for the SAGE application.
Manages worker processes and centralized background scheduler for health monitoring and session cleanup.
"""
import os
from apscheduler.schedulers.background import BackgroundScheduler
from run import health_monitor_job, cleanup_expired_sessions, SESSION_TTL_SECONDS


# =============================================================================
# Gunicorn Server Settings
# =============================================================================
bind = "0.0.0.0:8000"
timeout = 120  # Increased timeout for GPT-5/slow AI responses (default is 30s)
workers = 4    # Number of worker processes (2x CPU cores for P0V3 with 4 vCPU)
threads = 4    # Threads per worker (total: 16 concurrent requests per instance)
graceful_timeout = 30
keepalive = 5

# Prevent workers from starting their own schedulers
# The scheduler is managed centrally by gunicorn hooks (when_ready/on_exit)
preload_app = False  # Each worker loads app separately, but scheduler runs only in master

scheduler = None  # Define the scheduler globally

# Gunicorn hook to run when the server is ready (runs ONCE in master process)
def when_ready(server):
    """
    Hook to start the centralized scheduler when the Gunicorn server is ready.
    This runs only in the master process, not in workers, preventing duplicate jobs.
    
    IMPORTANT: Imports from main.py are deferred here to avoid circular imports
    and prevent the Flask app from initializing before Gunicorn is ready.
    """
    global scheduler

    # Read interval from environment variable, default to 30 if not set
    HEALTH_MONITOR_INTERVAL_MINUTES = int(os.getenv("HEALTH_MONITOR_INTERVAL_MINUTES", 30))
    SESSION_CLEANUP_INTERVAL_MINUTES = 15
    
    # Start the centralized scheduler
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(health_monitor_job, 'interval', minutes=HEALTH_MONITOR_INTERVAL_MINUTES, id='health_monitor')
    scheduler.add_job(cleanup_expired_sessions, 'interval', minutes=SESSION_CLEANUP_INTERVAL_MINUTES, id='session_cleanup')
    scheduler.start()
    
    server.log.info(f"Centralized scheduler started (health: {HEALTH_MONITOR_INTERVAL_MINUTES}min, session cleanup: {SESSION_CLEANUP_INTERVAL_MINUTES}min, TTL: {SESSION_TTL_SECONDS}s)")

# Gunicorn hook to run when the server is exiting
def on_exit(server):
    """
    Hook to shut down the scheduler when the Gunicorn server is exiting.
    """
    global scheduler
    # Shut down the scheduler when Gunicorn exits
    if scheduler:
        scheduler.shutdown()
        server.log.info("Centralized scheduler stopped")
