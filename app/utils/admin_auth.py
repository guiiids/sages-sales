import os
from functools import wraps

from flask import abort

from app.utils.auth_util import get_azure_user_info


# Decorator to require admin access for a route
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Logic: Check if user is logged in AND is an admin
        if not is_admin(get_azure_user_info().get('email')):
            # Return 403 Forbidden or redirect to login
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def is_admin(email):
    # Check if the given email is in the admin list
    admin_list = os.getenv("ADMIN_LIST", "gokul.bontha@non.agilent.com,dummy.user@agilent.com").split(",")
    # Return True if email is in admin list, else False
    if email in admin_list:
        return True
    return False