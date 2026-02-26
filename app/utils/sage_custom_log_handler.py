# sage_custom_log_handler.py

import logging
from logging import NOTSET
import sys
import threading
import time

from app.utils import notification_util


class SageCustomLogHandler(logging.Handler):
    """
    Custom logging handler that sends log records as notifications via email and Teams.
    Custom logging handler that reports the first occurrence of each unique log immediately,
    then batches all logs every 6 hours.
    """

    def __init__(self, level=NOTSET, interval_seconds=21600):
        """
        Initialize the handler.

        Args:
            level: Logging level.
            interval_seconds: Interval in seconds to batch and send logs (default 6 hours).
        """
        super().__init__(level)
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()  # Ensures thread-safe access to buffer and keys
        self._buffer = {}              # Stores log records for batching
        self._buffer_keys = set()      # Tracks unique log keys in the current batch
        self._start_timer()            # Starts the periodic batch notification thread

    def emit(self, record):
        """
        Process a log record.

        - If the log is unique in the current batch, notify immediately.
        - Add every log to the buffer for the next batch notification.
        """
        key = (record.module, record.lineno)
        with self._lock:
            if key not in self._buffer_keys:
                # First occurrence: notify immediately
                try:
                    self._notify([(record,0)])
                except Exception as e:
                    sys.stderr.write(f"Failed to send log notification: {e}\n")
                self._buffer_keys.add(key)
            # Add the log record to the buffer for batch notification
            rec,count = self._buffer.get(key, (None,0))
            self._buffer[key] = (record,count+1)

    def _start_timer(self):
        """
        Start a background thread to send batch notifications at the configured interval.
        """
        def notify_periodically():
            while True:
                time.sleep(self.interval_seconds)
                self._send_buffered_logs()
        t = threading.Thread(target=notify_periodically, daemon=True)
        t.start()

    def _send_buffered_logs(self):
        """
        Send all buffered logs as a batch notification and clear the buffer and keys.
        """
        with self._lock:
            if not self._buffer:
                return
            try:
                # Build and send the batch notification
                self._notify(self._buffer.values())
            except Exception as e:
                sys.stderr.write(f"Failed to send batch log notification: {e}\n")
            finally:
                # Clear buffer and keys for the next interval
                self._buffer.clear()
                self._buffer_keys.clear()

    def _notify(self, records):
        """
        Build notification payload and send using notification_util.

        Steps:
        1. Format the log record into a payload.
        2. Create a NotificationTemplate for email and Teams.
        3. Send the notification.
        """
        # Build the payload for the notification from the log record
        payload = notification_util.build_log_record_card_data(records)

        # Create a notification template for both email and Teams
        log_notification = notification_util.NotificationTemplate(
            payload,
            is_adaptive_card=True,
            is_email=True,
            is_teams=True
        )

        # Send the notification using notification_util
        notification_util.send_notification(log_notification)
