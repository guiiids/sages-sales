#app/Connection.py
# =====================================================================================================#
#Copyright (c) 2026 Agilent Technologies All rights reserved worldwide.
#Agilent Confidential, Use is permitted only in accordance with applicable End User License Agreement.
# =====================================================================================================#

# Description: This module provides a database connection with thread-safe scoped sessions.
import logging
import os

from app.persistence.db_api import Connection

logger = logging.getLogger(__name__)

# Module-level singleton: engine + scoped_session factory (created once, thread-safe)
_connection = None


def get_connection():
    """
    Returns a Connection instance with a thread-safe scoped_session.
    The Connection is created once; each thread gets its own Session.
    :return: An instance of a database connection.
    """
    global _connection
    if _connection is None:
        db_hostname = os.getenv("POSTGRES_HOST")
        db_port = os.getenv("POSTGRES_PORT")
        db_username = os.getenv("POSTGRES_USER")
        db_password = os.getenv("POSTGRES_PASSWORD")
        db_database = os.getenv("POSTGRES_DB")
        db_ssl_mode = os.getenv("POSTGRES_SSL_MODE", "disable")
        _connection = Connection(
            db_hostname, db_port, db_username, db_password, db_database,
            schema_name="public", ssl_mode=db_ssl_mode
        )
        logger.info("Database connection created with scoped_session")
    # Ensure the current thread's session is healthy before returning
    _connection.ensure_healthy_session()
    return _connection