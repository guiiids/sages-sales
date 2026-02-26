# notification_util.py
import concurrent
import json
import logging
import os
import smtplib
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import urllib3

logger = logging.getLogger(__name__)

# Disable SSL warnings for local dev (corporate proxy issues)
def _get_ssl_verify():
    """Returns False for local dev to bypass corporate proxy SSL issues."""
    # Check multiple sources for local environment detection
    env = os.environ.get('FLASK_ENV', '').lower()
    ragka_env = os.environ.get('RAGKA_ENV', '').lower()
    website_hostname = os.environ.get('WEBSITE_HOSTNAME', '')
    
    # Is local if:
    # 1. FLASK_ENV is development/local
    # 2. RAGKA_ENV is local/dev
    # 3. No WEBSITE_HOSTNAME (not in Azure)
    is_local = (
        env in ('development', 'local') or 
        ragka_env in ('local', 'dev', 'development') or
        not website_hostname  # No Azure hostname = local dev
    )
    
    if is_local:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.debug("SSL verification disabled for local development")
        return False
    return True

def send_message_in_teams(payload, teams_webhook_url=None):
    """
    Sends a message to a Microsoft Teams channel via webhook.
    """
    if teams_webhook_url:
        notify_via_webhook(payload, teams_webhook_url)
    else:
        logger.info("No webhook URL provided. Failed to send message.")

def notify_via_webhook(payload, webhook_url=None):
    """
    Sends a generic payload to a specified webhook URL.
    """
    if webhook_url:
        session = requests.Session()
        # Use the shared session for requests
        try:
            response = session.post(webhook_url, json=payload, verify=_get_ssl_verify())
            response.raise_for_status()
            if response.status_code in (200, 202):
                logger.info("Payload sent successfully!")
            else:
                logger.info(f"Failed to send payload. Status code: {response.status_code}, Response: {response.text}")
        except requests.exceptions.RequestException as e:
            logger.info(f"An error occurred: {e}")
    else:
        logger.info("No webhook URL provided. Failed to send payload.")

def send_email_using_powerautomate(subject, body, to_list=None, power_automate_webhook_url=None):
    """
    Sends an email using Power Automate via webhook.
    """
    payload = {"RecipientEmail": ', '.join(to_list), "Subject": subject, "BodyContent": body}
    if power_automate_webhook_url:

        notify_via_webhook(payload, power_automate_webhook_url)
    else:
        logger.info("No Power Automate webhook URL provided. Failed to send email.")

def send_email(subject, payload, to_list=None, is_adaptive_card=False):
    """
    Sends an Adaptive Card payload as an HTML email.
    """
    try:
        html = payload
        if is_adaptive_card:
            card = payload["attachments"][0]["content"]
            html = f"<h2>{card.get('body', [{}])[0].get('text', '')}</h2>"
            for block in card.get("body", [])[1:]:
                if block["type"] == "TextBlock":
                    color = block.get("color", "Default")
                    color_map = {
                        "Good": "#107C10",
                        "Warning": "#FFAA44",
                        "Attention": "#D13438",
                        "Default": "#333333"
                    }
                    html_color = color_map.get(color, "#333333")
                    if block.get('separator', False):
                        html += "<hr>"
                    else:
                        html += f"<p style='color:{html_color}'>{block.get('text', '')}</p>"

        # Load email config from environment
        from_email = os.environ.get("SMTP_FROM_EMAIL")
        #app_password = os.environ.get("SMTP_APP_PASSWORD")
        smtp_server = os.environ.get("SMTP_SERVER")
        smtp_port = int(os.environ.get("SMTP_PORT"))
        #smtp_secure = bool(os.environ.get("SMTP_SECURE", True))

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = ', '.join(to_list)
        msg.attach(MIMEText(html, "html"))

        # Connect to SMTP server

        if smtp_server and smtp_port and from_email and to_list :
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)

            """
            Followed code is for secure connection and authentication if needed.
            It is not required for SMTP relay without auth.
            """
            # Create a secure SSL context
            # context = ssl._create_unverified_context()

            # if smtp_secure:
            #     server.starttls(context=context)
            # if app_password:
            #     server.login(from_email, app_password)

            # Send email
            server.sendmail(from_email, to_list, msg.as_string())
            logger.info("✅ Email sent successfully!")
            server.quit()
        elif power_automate_webhook_url := os.environ.get('POWER_AUTOMATE_WEBHOOK_URL'):
            logger.info("Sending Email notification through webhook")
            send_email_using_powerautomate(subject, html, to_list, power_automate_webhook_url)
        else:
            logger.info("No webhook URL or SMTP configuration provided. Failed to send email.")
    except (smtplib.SMTPException, socket.timeout, OSError) as e:
        logger.info(f"SMTP server not reachable or timed out: {e}")
    except Exception as e:
        logger.info(f"An error occurred: {e}")

def build_adaptive_card_payload(card_data: dict) -> dict:
    """
    Builds a Microsoft Teams Adaptive Card payload from a standardized card_data dict.
    """
    host_name = os.environ.get("WEBSITE_HOSTNAME") or "localhost"
    body = [{
        "type": "TextBlock",
        "text": card_data.get('title', ''),
        "weight": "Bolder",
        "size": "Large"
    }, {
        "type": "TextBlock",
        "text": f"Server : {host_name}",
        "color": "Accent",
        "wrap": True
    }]
    # Add fields to the card body
    for field in card_data.get("fields", []):
        if field.get('is_separator', False):
            body.append({"type": "TextBlock", "text": " ", "separator": True, "spacing": "Medium"})
        else:
            body.append({
                "type": "TextBlock",
                "text": f"{field.get('icon', '')} {field['label']}: {field['value']}",
                "color": field.get("color", "Default"),
                "wrap": True
            })
    # Add sections to the card body
    for section_title, fields in card_data.get("sections", {}).items():
        body.append({
            "type": "TextBlock",
            "text": section_title,
            "weight": "Bolder",
            "spacing": "Medium"
        })
        for field in fields:
            if field.get('is_separator', False):
                body.append({"type": "TextBlock", "text": " ", "separator": True, "spacing": "Medium"})
            else:
                body.append({
                    "type": "TextBlock",
                    "text": f"{field.get('icon', '')} {field['label']}: {field['value']}",
                    "color": field.get("color", "Default"),
                    "wrap": True
                })
    # Construct the final payload
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": body
                }
            }
        ]
    }
    return payload

def build_health_check_card_data(message):
    """
    Builds card data for health check notifications.
    """
    def get_color(val):
        try:
            v = float(val)
            if v < 70:
                return "Good"
            elif v < 90:
                return "Warning"
            else:
                return "Attention"
        except Exception:
            return "Default"

    def get_status_icon(status):
        return "✅" if str(status).lower() in ["ok", "green"] else "❌"

    def get_status_color(status):
        return "Good" if str(status).lower() in ["ok", "green"] else "Attention"

    system = message.get("system", {})
    external = message.get("external", {})

    card_data = {
        "title": "SAGE Health Check",

        "fields": [
            {"is_separator": True},
            {"label": "Status", "value": message.get("status", "N/A"), "color": get_status_color(message.get("status", "N/A"))},
            {"label": "Version", "value": message.get("version", "N/A")},
            {"label": "Checked", "value": datetime.now(timezone.utc).strftime('%d %b %Y %H:%M:%S UTC')}
        ],
        "sections": {
            "System Metrics": [
                {"is_separator": True},
                {"label": "CPU", "value": f"{system.get('cpu_percent', 'N/A')}%", "icon": "💻", "color": get_color(system.get('cpu_percent', 'N/A'))},
                {"label": "Memory", "value": f"{system.get('memory_percent', 'N/A')}%", "icon": "🧠", "color": get_color(system.get('memory_percent', 'N/A'))},
                {"label": "Disk", "value": f"{system.get('disk_percent', 'N/A')}%", "icon": "💾", "color": get_color(system.get('disk_percent', 'N/A'))},
                {"label": "Status", "value": system.get("status", "N/A"), "color": get_status_color(system.get("status", "N/A"))},
                {"is_separator": True}
            ],
            "External Services": [
                {
                    "label": key.replace("_", " ").title(),
                    "value": val.get("status", "N/A"),
                    "icon": get_status_icon(val.get("status", "N/A")),
                    "color": get_status_color(val.get("status", "N/A")),
                    "details": ", ".join(f"{k}: {v}" for k, v in val.items() if k != "status")
                }
                for key, val in external.items()
            ]
        }
    }
    return card_data

def build_log_record_card_data(log_records_with_count: list):
    """
    Builds card data for a batch of log record notifications.
    """
    fields = []
    title = "📢 Log Alert in SAGE"
    timestamp_label = "Time Stamp"
    if len(log_records_with_count) > 1 or list(log_records_with_count)[0][1] > 0:
        title = "📢 Batch Log Alerts in SAGE"
        timestamp_label = "Last Reported Time Stamp"
    for log_record,count in log_records_with_count:
        # Add a separator for log records
        fields.append({"is_separator": True})
        fields.append({"label": "Logger", "value": log_record.name})
        fields.append({"label": "Level", "value": log_record.levelname, "color": "Attention"})
        if count > 0:
            fields.append({"label": "Occurrence", "value": count})
        fields.append({"label": timestamp_label,
                       "value": datetime.fromtimestamp(log_record.created, tz=timezone.utc).strftime(
                           '%d %b %Y %H:%M:%S:%f UTC')})
        fields.append({"label": "Module", "value": log_record.module})
        fields.append({"label": "Line", "value": log_record.lineno})
        fields.append({"label": "Error", "value": log_record.getMessage()})

    return {
        "title": title,
        "fields": fields
    }

def send_notification(notification_template: 'NotificationTemplate'):
    """
    Sends notifications based on the NotificationTemplate.
    Uses ThreadPoolExecutor for parallelism and a shared requests.Session for Teams.
    """
    # Get deployment environment
    deployment_env = os.environ.get("FLASK_ENV") or "Development"
    payload = notification_template.to_dict()
    notification_payload = None

    # Append environment to title for clarity from which environment the notification is sent
    payload["notification_payload"]['title'] = f"{payload['notification_payload']['title']} ({deployment_env})"

    if payload["is_adaptive_card"]:
        notification_payload = build_adaptive_card_payload(payload["notification_payload"])

    # Check if notifications are to be skipped
    skip_notifications = os.environ.get("SKIP_NOTIFICATIONS", "False").lower() == "true"

    # Skip sending notifications if configured to do so and log the payload
    if skip_notifications:
        logger.info("Notifications are skipped as per configuration.")
        logger.info("--------- Notification Payload ---------")
        logger.info(json.dumps(notification_payload, indent=2))
        logger.info("----------------------------------------")
        return

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []

        # Teams notification task
        if "teams" in payload["notification_type"] and payload["teams_to_list"]:
            session = requests.Session()
            def send_teams():
                for teams_webhook in payload["teams_to_list"]:
                    logger.info("Sending Teams notification through webhook")
                    send_message_in_teams(notification_payload, teams_webhook)
            futures.append(executor.submit(send_teams))

        # Email notification task
        if "email" in payload["notification_type"] and payload["email_to_list"]:
            def send_email_task():
                title = payload["notification_payload"]['title']
                send_email(title, notification_payload, to_list=payload["email_to_list"],
                           is_adaptive_card=payload["is_adaptive_card"])

            # Submit the email task to the thread pool
            future = executor.submit(send_email_task)
            # Wait for the email task to complete, with a 35-second timeout
            done, not_done = concurrent.futures.wait([future], timeout=35)
            # If the task did not complete in time, log a timeout message
            if not_done:
                logger.info("Email sending task timed out after 35 seconds.")
            # Add the future to the list for later result checking
            futures.append(future)

        # Wait for all tasks to complete
        for future in futures:
            future.result()


class NotificationTemplate:
    """
    Template class for notification configuration.
    Determines recipients and notification types from environment variables.
    """
    def __init__(self, notification_payload, is_adaptive_card=False, is_email=True, is_teams=False):
        self.notification_payload = notification_payload
        self.is_adaptive_card = is_adaptive_card
        self.notification_type = []
        self.email_to_list = []
        self.teams_to_list = []

        if is_email:
            self.notification_type.append("email")
            email_list = os.environ.get("EMAIL_TO_LIST", "")
            self.email_to_list = [e.strip() for e in email_list.split(",") if e.strip()]
        if is_teams:
            self.notification_type.append("teams")
            teams_list = os.environ.get("TEAMS_WEBHOOK_LIST", "")
            self.teams_to_list = [t.strip() for t in teams_list.split(",") if t.strip()]

    def to_dict(self):
        """
        Returns the notification template as a dictionary.
        """
        return {
            "email_to_list": self.email_to_list,
            "teams_to_list": self.teams_to_list,
            "notification_type": self.notification_type,
            "notification_payload": self.notification_payload,
            "is_adaptive_card": self.is_adaptive_card
        }
