import base64
import concurrent
import logging
import os
import re
import time
import urllib
from urllib.parse import urlunparse, urlparse

import psutil
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient
from flask import g, session
from openai import AzureOpenAI

from app.Connection import get_connection

# Configure logger
logger = logging.getLogger(__name__)


def full_health_check():
    """
    Perform a full health check of all external services and system resources.
    Runs checks in parallel for efficiency.
    :return: (overall_status, response_dict)
    """
    start_time = time.time()

    # Define individual checks
    # Each check returns a tuple of (key, result_dict)

    # Check Azure OpenAI
    def check_azure_openai():
        try:
            client = AzureOpenAI(
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_KEY"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
            )
            models = list(client.models.list())
            return ("azure_openai", {
                "status": "ok",
                "models_count": len(models),
            })
        except Exception as e:
            logger.error(f"Error connecting to Azure OpenAI: {e}");
            return ("azure_openai", {
                "status": "error",
                "error": "Azure OpenAI connection failed"
            })

    # Check Azure Blob Storage
    def check_azure_blob():
        try:
            conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            if conn_str:
                conn_str = conn_str.strip('"\'')
            blob_service_client = BlobServiceClient.from_connection_string(conn_str)
            containers = list(blob_service_client.list_containers())
            return ("azure_blob", {
                "status": "ok",
                "containers_count": len(containers),
            })
        except Exception as e:
            logger.error(f"Error connecting to Azure Blob: {e}");
            return ("azure_blob", {
                "status": "error",
                "error": "Azure Blob connection failed"
            })

    # Check Azure Cognitive Search
    def check_azure_search():
        try:
            search_client = SearchClient(
                endpoint=os.getenv("AZURE_SEARCH_SERVICE"),
                index_name=os.getenv("AZURE_SEARCH_INDEX"),
                credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY")),
            )
            indexes = search_client.get_document_count()
            return ("azure_search", {
                "status": "ok",
                "indexes_count": indexes,
            })
        except Exception as e:
            logger.error(f"Error connecting to Azure Search: {e}");
            return ("azure_search", {
                "status": "error",
                "error": "Azure Search connection failed",
            })

    # Check Database connectivity
    def check_database():
        try:
            conn = get_connection()
            if conn.test_connection():
                return ("database", {
                    "status": "ok",
                })
            else:
                return ("database", {
                    "status": "error",
                    "error": "Database connection failed",
                })
        except Exception as e:
            logger.error(f"Error connecting to Database: {e}");
            return ("database", {
                "status": "error",
                "error": "Database connection failed",
            })

    # Check system resources (CPU, memory, disk)
    def check_system_resources():
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            # Thresholds: >90% is warning
            if cpu_percent > 90 or mem.percent > 90 or disk.percent > 90:
                status_val = "warning"
            else:
                status_val = "ok"
            return ("system", {
                "status": status_val,
                "cpu_percent": cpu_percent,
                "memory_percent": mem.percent,
                "disk_percent": disk.percent,
            })
        except Exception as e:
            logger.error(f"System resources error: {e}")
            return ("system", {
                "status": "error",
                "error": "System resources check failed",
            })

    checks = [
        check_system_resources,
        check_azure_openai,
        check_azure_blob,
        check_azure_search,
        check_database
    ]

    # Run checks in parallel
    results = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_check = {executor.submit(fn): fn.__name__ for fn in checks}
        for future in concurrent.futures.as_completed(future_to_check):
            key, result = future.result()
            results[key] = result

    # Build external and system sections
    system = results.get("system", {})
    external = {
        "azure_openai": results.get("azure_openai", {}),
        "azure_blob": results.get("azure_blob", {}),
        "azure_search": results.get("azure_search", {}),
        "database": results.get("database", {})
    }

    # Determine overall status
    all_statuses = [system.get("status", "error")] + [v.get("status", "error") for v in external.values()]
    if all(x == "ok" for x in all_statuses):
        overall_status = "green"
    elif any(x == "warning" for x in all_statuses):
        overall_status = "yellow"
    else:
        overall_status = "red"

    response = {
        "name": "sage",
        "version": os.getenv("APP_VERSION"),
        "status": overall_status,
        "system": system,
        "external": external
    }
    return overall_status, response

def get_source_doc(parent_id):
    search_client = SearchClient(
        endpoint=os.getenv("AZURE_SEARCH_SERVICE"),
        index_name=os.getenv("AZURE_SEARCH_INDEX"),
        credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY")),
    )

    try:
        results = search_client.search(search_text="*", filter=f"parent_id eq '{parent_id}'", select=["source"],
                                       top=1, )
        source_url = None
        for doc in results:
            if "source" in doc:
                source_url = doc.get("source")
                break
    except Exception as e:
        logger.error(f"Error retrieving source document from search index: {e}")
        source_url = None
    return source_url


def custom_base64_decode(input_str):
    """
    Decode a base64-encoded URL string with robust error handling.
    Handles cases where the base64 string has trailing garbage characters.
    """
    if not input_str:
        return ''

    # Remove any non-base64 characters from the end of the string
    clean_input = re.sub(r'[^A-Za-z0-9+/=]+$', '', input_str)

    def try_decode(s):
        """Attempt to decode a base64 string, returning None on failure."""
        try:
            # Add padding if needed
            padded = s + '=' * ((4 - len(s) % 4) % 4)
            decoded_bytes = base64.b64decode(padded)
            return decoded_bytes.decode('utf-8')
        except Exception:
            return None

    # Try decoding as-is first
    decoded = try_decode(clean_input)

    # If decode failed or result doesn't look like a URL, try trimming trailing characters
    # This handles cases where Azure Search appends extra characters to the parent_id
    if decoded is None or "http" not in decoded.lower():
        # Try removing trailing characters one at a time (up to 4 chars to handle padding issues)
        for trim_count in range(1, 5):
            if len(clean_input) > trim_count:
                trimmed = clean_input[:-trim_count]
                result = try_decode(trimmed)
                if result and "http" in result.lower():
                    decoded = result
                    logger.debug(f"Successfully decoded after trimming {trim_count} char(s): {result[:100]}...")
                    break

    # If still no valid URL, try URL-safe base64 variant
    if decoded is None or "http" not in decoded.lower():
        try:
            # Convert URL-safe base64 to standard base64
            url_safe_input = clean_input.replace('-', '+').replace('_', '/')
            padded = url_safe_input + '=' * ((4 - len(url_safe_input) % 4) % 4)
            decoded_bytes = base64.b64decode(padded)
            percent_encoded = ''.join('%%%02x' % b for b in decoded_bytes)
            decoded = urllib.parse.unquote(percent_encoded)
        except Exception:
            pass

    # If all decoding attempts failed, return original input
    if decoded is None:
        logger.warning(f"Failed to decode base64 URL: {input_str[:50]}...")
        return input_str

    # Clean up the decoded URL - extract just the file URL
    cleaned = decoded
    m = re.search(r'https?://.*?\.(pdf|txt|csv|docx?|xlsx?)(?:\?[^\"\']*)?', decoded, re.IGNORECASE)
    if m:
        matched = m.group(0)
        # Remove any query parameters for cleaner URL
        cleaned = matched.split('?')[0]

    return cleaned


def remove_host_from_url(url):
    """
    Removes the scheme and network location (host and port) from a given URL.

    Args:
        url (str): The input URL string.

    Returns:
        str: The URL with the host removed, or an empty string if the input is invalid.
    """
    parsed_url = urlparse(url)
    # Create a new ParseResult object with empty scheme and netloc
    # and reconstruct the URL from the remaining components (path, params, query, fragment)
    new_parsed_url = parsed_url._replace(scheme='', netloc='')
    return urlunparse(new_parsed_url)

def _get_user_id():
    """Safely get user_id from Flask g context, returns None if unavailable."""
    try:
        return g.user_info.get("user_id") or None
    except (RuntimeError, AttributeError):
        return None
        
def get_user_name(user_info):
    if user_info is None:
        return user_info
    user_name = user_info.get("name") if user_info else "User"
    # Formatting name to first name only in camel case, from full name like "last_name,first_name (company)"
    if "," in user_name:
        first_name_part = user_name.split(",")[1]
        last_name_part = user_name.split(",")[0]
        user_name = first_name_part.strip()+" "+last_name_part.strip()

    user_name = user_name.strip().capitalize()
    return user_name

def clean_session_in_db(session_id):
    """
    Clear the session based on the session ID in DB
    """
    if session_id:
        connection = get_connection()
        connection.set_session_end_time(session_id)

def clean_session(session_id):
    """
    Clear the session based on the session ID
    """
    from app.utils.rag_util import clear_rag_assistant
    status = clear_rag_assistant(session_id)
    clean_session_in_db(session_id)
    session.clear()
    session["__invalidate__"] = True