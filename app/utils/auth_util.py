import base64
import hashlib
import json
import logging

import requests
from flask import request

from app.Connection import get_connection
from app.models.models import User, UserDetails

logger = logging.getLogger(__name__)


def _get_request_ip() -> str:
    """Best-effort client IP resolution behind proxies."""
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    real_ip = request.headers.get('X-Client-Ip')
    
    if real_ip:
        return real_ip.strip()
    return request.remote_addr or 'unknown'

# Helper to get location from Microsoft Graph if not present in claims
def get_location_from_graph(ad_user_id, access_token):
    """
    Fetches user's location from Microsoft Graph API using their object id and access token.
    """
    if not ad_user_id or not access_token:
        logger.warning("Missing ad_user_id or access_token for Graph API call.")
        return None
    url = f"https://graph.microsoft.com/v1.0/users/{ad_user_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    logger.info(f"Requesting location from Graph API for ad_user_id: {ad_user_id}")
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        # Try to get officeLocation or city or country
        return data.get("officeLocation") or data.get("city") or data.get("country")
        location = data.get("officeLocation") or data.get("city") or data.get("country")
        logger.info(f"Location fetched from Graph API: {location}")
        return location
    logger.error(f"Failed to fetch location from Graph API. Status: {response.status_code}")
    return None

def get_azure_user_info():
    """
    Extracts user info from Azure App Service Authentication headers.
    Returns a dict with ad_user_id, name, email, and location (if available or via Graph).
    """
    principal_header = request.headers.get('X-MS-CLIENT-PRINCIPAL')
    if not principal_header:
        logger.warning("No X-MS-CLIENT-PRINCIPAL header found in request.")
        # ip_addr = _get_request_ip()
        # logger.info(f"User ip address: {ip_addr}")
        # Dummy data for un-authentication env
        user_info = {
            'ad_user_id':'dummy_ad_user_id',
            'name' : 'Dummy,User ',
            'email' : 'dummy.user@agilent.com',
            'location' : 'dummy'
        }

    else:
        # Decode the base64-encoded JSON
        try:
            decoded = base64.b64decode(principal_header)
            principal = json.loads(decoded)
        except Exception as e:
            logger.error(f"Failed to decode principal header: {e}")
            return None

        # Extract claims
        claims = {claim['typ']: claim['val'] for claim in principal.get('claims', [])}
        ad_user_id = claims.get('http://schemas.microsoft.com/identity/claims/objectidentifier')
        name = claims.get('name')
        email = claims.get('http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress')
        location = claims.get('location')  # Only if your app sets this claim

        # Use CountryName cookie as a fallback before calling Graph API
        if not location:
            country_cookie = request.cookies.get('CountryName')
            if country_cookie:
                logger.info(f"CountryName cookie found: {country_cookie}")
                location = country_cookie

        # X-MS-TOKEN-AAD-ACCESS-TOKEN is not available to call Graph API in this context
        # So we will not attempt to call Graph API here

        # # If location is not present, try to get it from Graph API
        # logger.info(f"Extracted claims for ad_user_id: {ad_user_id}, name: {name}, email: {email}")
        #
        # if not location:
        #     # Get access token from header (App Service provides it if configured)
        #     access_token = request.headers.get('X-MS-TOKEN-AAD-ACCESS-TOKEN')
        #     # Log all request headers (redacted) for debugging instead of printing raw token
        #     log_all_request_headers(request.headers)
        #     logger.info("Location not found in claims, attempting to fetch from Graph API.")
        #     location = get_location_from_graph(ad_user_id, access_token)
        user_info= {
            'ad_user_id': ad_user_id,
            'name': name,
            'email': email,
            'location': location
        }
    user_info = save_user_to_db(user_info)
    return user_info

def log_all_request_headers(headers, reveal_sensitive=True) -> None:
    """
    Logs request headers. If `reveal_sensitive` is True logs full header values (useful for debugging).
    If False, sensitive headers (auth, token, cookie, etc.) are partially redacted.
    """
    try:
        def _to_str(v):
            if v is None:
                return None
            if isinstance(v, (bytes, bytearray)):
                try:
                    return v.decode("utf-8", errors="ignore")
                except Exception:
                    return str(v)
            return str(v)

        def _is_sensitive(name: str) -> bool:
            name_l = (name or "").lower()
            return any(k in name_l for k in (
                "authorization", "token", "cookie", "set-cookie", "password",
                "x-ms-token", "x-ms-token-aad", "x-ms-client-principal"
            ))

        def _format_value(name: str, value):
            s = _to_str(value)
            if not reveal_sensitive and _is_sensitive(name):
                return (s[:6] + "...") if len(s) > 6 else "REDACTED"
            # truncate extremely long values to avoid huge logs
            return s if len(s) <= 2000 else s[:2000] + "..."

        formatted = {k: _format_value(k, v) for k, v in headers.items()}
        logger.info("Request headers: %s", json.dumps(formatted))
    except Exception:
        logger.exception("Failed to log request headers")

def save_user_to_db(user_info):
    """
    Saves the user in the database if not exists, else updates last_login.
    Checks for existing user using encrypted ad_user_id to avoid duplicates.
    """
    if not user_info or not user_info['ad_user_id']:
        logger.warning("No user_info or ad_user_id provided to save_user_to_db.")
        return

    user_info['ad_user_id_hash'] = hashlib.sha256(user_info['ad_user_id'].encode()).hexdigest()

    connection = get_connection()

    # Query using the encrypted value (private attribute)
    user = connection.get_user_by_ad_user_id_hash(user_info['ad_user_id_hash'])
    logger.info(f"Saving user to DB: {user_info['ad_user_id']}, {user_info['email']}")
    if user:
        user.location = user_info['location']
    else:
        user = User(
            ad_user_id=user_info['ad_user_id'],
            ad_user_id_hash=user_info['ad_user_id_hash'],
            details=UserDetails(
                user_name=user_info.get('name'),
                user_email=user_info.get('email'),
                location=user_info.get('location')
            )

        )
    connection.save_user(user)
    logger.info(f"Created/Updated user in DB. {user.user_id}")
    return {
        'user_id': user.user_id,
        'ad_user_id': user.ad_user_id,
        'name': user.details.user_name if user.details else None,
        'email': user.details.user_email if user.details else None,
        'location': user.details.location if user.details else None
    }

def is_user_in_DB(user_info):
    """
    Checks if user exists in DB using encrypted ad_user_id. If user exists, returns True, else False.
    """
    if not user_info or not user_info['ad_user_id']:
        logger.warning("No user_info or ad_user_id provided to is_user_in_DB.")
        return False
    user_info['ad_user_id_hash'] = hashlib.sha256(user_info['ad_user_id'].encode()).hexdigest()
    connection = get_connection()
    user = connection.get_user_by_ad_user_id_hash(user_info['ad_user_id_hash'])
    return user is not None


    # # Query for existing user
    # user = User.query.filter_by(ad_user_id=user_info['ad_user_id']).first()
    # if not user:
    #     # Create new user
    #     logger.info("User not found in DB. Creating new user.")
    #     user = User(ad_user_id=user_info['ad_user_id'], name=user_info['name'], email=user_info['email'], location=user_info['location'], last_login=datetime.utcnow())
    #     db.session.add(user)
    # else:
    #     # Update last_login only
    #     logger.info("User exists. Updating last_login.")
    #     user.last_login = datetime.utcnow()
    # db.session.commit()
