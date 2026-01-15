# Firebase Session Authentication for HackPSU Integration
# This module handles authentication with HackPSU's Firebase-based session auth

import os
import jwt
import logging
import requests
import time
from functools import wraps
from flask import request, session, redirect, render_template, url_for
from gavel.models import Annotator, db
from gavel import app

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Also log to stdout for Docker
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(levelname)s] %(name)s: %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

# Environment configuration
AUTH_LOGIN_URL = os.environ.get('AUTH_LOGIN_URL', 'http://localhost:3000/login')
AUTH_ENVIRONMENT = os.environ.get('AUTH_ENVIRONMENT', 'production')
MIN_JUDGE_ROLE = int(os.environ.get('MIN_JUDGE_ROLE', '2'))  # Only users with role >= 2 can judge
MIN_ADMIN_ROLE = int(os.environ.get('MIN_ADMIN_ROLE', '4'))  # Only users with role >= 4 can access admin

# Firebase configuration
FIREBASE_PROJECT_ID = os.environ.get('FIREBASE_PROJECT_ID', 'hackpsu-408118')
FIREBASE_API_KEY = os.environ.get('FIREBASE_API_KEY', 'AIzaSyBG636oXijUAzCq6Makd2DNU_0WzPJRw8s')

# Initialize Firebase Admin SDK
firebase_admin_app = None
firebase_has_service_account = False
try:
    import firebase_admin
    from firebase_admin import credentials, auth as firebase_auth

    # Check if already initialized
    try:
        firebase_admin_app = firebase_admin.get_app()
        logger.info("Firebase Admin SDK already initialized")
        firebase_has_service_account = True  # Assume it was initialized with credentials
    except ValueError:
        # Not initialized, try to find service account
        service_account_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

        # Also check common locations if env var not set or file doesn't exist
        possible_paths = [
            service_account_path,
            '/app/firebase-service-account.json',  # Docker mount location
            './firebase-service-account.json',  # Local dev
            os.path.join(os.path.dirname(__file__), '..', 'firebase-service-account.json'),
        ]

        cred = None
        used_path = None
        for path in possible_paths:
            if path and os.path.exists(path):
                try:
                    cred = credentials.Certificate(path)
                    used_path = path
                    break
                except Exception as e:
                    logger.warning(f"Failed to load service account from {path}: {e}")

        if cred:
            firebase_admin_app = firebase_admin.initialize_app(cred)
            firebase_has_service_account = True
            logger.info(f"Firebase Admin SDK initialized with service account: {used_path}")
        else:
            # Initialize with just project ID - limited functionality (no custom token creation)
            firebase_admin_app = firebase_admin.initialize_app(options={'projectId': FIREBASE_PROJECT_ID})
            logger.warning(
                f"Firebase Admin SDK initialized with project ID only (no service account). "
                f"Token generation for API calls will not work. "
                f"Place firebase-service-account.json in the project root to enable sync."
            )
except ImportError:
    logger.warning("firebase-admin not installed, falling back to JWT decode only")
    firebase_auth = None
except Exception as e:
    logger.warning(f"Firebase Admin SDK initialization failed: {e}, falling back to JWT decode")
    firebase_auth = None

logger.info(f"Firebase Auth configured: AUTH_ENVIRONMENT={AUTH_ENVIRONMENT}, MIN_JUDGE_ROLE={MIN_JUDGE_ROLE}, MIN_ADMIN_ROLE={MIN_ADMIN_ROLE}")


def verify_session_cookie_with_admin(token_string):
    """Verify session cookie using Firebase Admin SDK.

    Returns decoded claims if valid, None otherwise.
    """
    if firebase_auth is None:
        logger.debug("Firebase Admin SDK not available, skipping admin verification")
        return None

    try:
        logger.debug("Attempting to verify session cookie with Firebase Admin SDK...")
        # verify_session_cookie checks signature, expiration, and revocation
        decoded = firebase_auth.verify_session_cookie(token_string, check_revoked=True)
        logger.info(f"Session cookie verified with Admin SDK: uid={decoded.get('uid')}, email={decoded.get('email')}")
        return decoded
    except firebase_auth.InvalidSessionCookieError as e:
        logger.warning(f"Invalid session cookie: {e}")
        return None
    except firebase_auth.ExpiredSessionCookieError:
        logger.warning("Session cookie has expired")
        return None
    except firebase_auth.RevokedSessionCookieError:
        logger.warning("Session cookie has been revoked")
        return None
    except Exception as e:
        logger.warning(f"Firebase Admin verification failed: {type(e).__name__}: {e}")
        return None


def decode_session_token(token_string):
    """Decode Firebase session JWT token.

    First tries Firebase Admin SDK for proper verification,
    then falls back to JWT decode without verification.
    """
    try:
        logger.debug(f"Attempting to decode token (length={len(token_string) if token_string else 0})")

        # Try Firebase Admin SDK first (proper verification)
        admin_decoded = verify_session_cookie_with_admin(token_string)
        if admin_decoded:
            return admin_decoded

        # Fall back to JWT decode without verification
        logger.debug("Falling back to JWT decode without verification")
        decoded = jwt.decode(token_string, options={"verify_signature": False})
        logger.debug(f"Token decoded successfully. Keys in token: {list(decoded.keys())}")
        # Log token contents (excluding sensitive data)
        safe_keys = ['email', 'name', 'displayName', 'user_id', 'sub', 'uid', 'production', 'staging', 'iat', 'exp', 'iss']
        safe_data = {k: decoded.get(k) for k in safe_keys if k in decoded}
        logger.info(f"Token data: {safe_data}")
        return decoded
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        return None
    except jwt.DecodeError as e:
        logger.error(f"Failed to decode token (invalid format): {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error decoding token: {type(e).__name__}: {e}")
        return None


def verify_hackpsu_session():
    """Verify session and extract user data from Firebase JWT token."""
    logger.debug(f"verify_hackpsu_session called for path: {request.path}")

    try:
        # Get session token from cookies
        session_token = request.cookies.get('__session')

        # Log all cookies for debugging (names only)
        cookie_names = list(request.cookies.keys())
        logger.debug(f"Available cookies: {cookie_names}")

        if not session_token:
            logger.warning("No __session cookie found in request")
            return None

        logger.debug(f"Found __session cookie (length={len(session_token)})")

        # Decode the session token to get user data
        user_data = decode_session_token(session_token)

        if not user_data:
            logger.warning("Failed to decode session token")
            return None

        # Extract relevant user info
        email = user_data.get('email', '')
        name = user_data.get('name') or user_data.get('displayName')

        # If no name, use email prefix
        if not name and email:
            name = email.split('@')[0]

        # Check for custom claims in different possible locations
        custom_claims = {}

        # Option 1: Direct fields (production/staging at root level)
        if 'production' in user_data or 'staging' in user_data:
            custom_claims = {
                'production': user_data.get('production', 0),
                'staging': user_data.get('staging', 0)
            }
            logger.debug(f"Found privilege levels at root level: {custom_claims}")

        # Option 2: Nested in customClaims
        elif 'customClaims' in user_data:
            custom_claims = user_data.get('customClaims', {})
            logger.debug(f"Found privilege levels in customClaims: {custom_claims}")

        # Option 3: Nested in claims
        elif 'claims' in user_data:
            custom_claims = user_data.get('claims', {})
            logger.debug(f"Found privilege levels in claims: {custom_claims}")

        else:
            logger.warning(f"No privilege levels found in token. Full token keys: {list(user_data.keys())}")
            # Log full token for debugging (be careful in production)
            logger.debug(f"Full token contents: {user_data}")

        user_info = {
            'uid': user_data.get('user_id') or user_data.get('sub'),
            'email': email,
            'displayName': name or 'Unknown User',
            'customClaims': custom_claims
        }

        logger.info(f"Extracted user info: uid={user_info['uid']}, email={user_info['email']}, claims={user_info['customClaims']}")

        if not user_info.get('uid') and not user_info.get('email'):
            logger.warning("No uid or email found in token - authentication failed")
            return None

        return user_info

    except Exception as e:
        logger.error(f"Session verification failed: {type(e).__name__}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def extract_user_privilege(user_data):
    """Extract role level from Firebase custom claims."""
    # Custom claims contain privilege levels for different environments
    custom_claims = user_data.get('customClaims', {})

    # Extract privilege for current environment (production or staging)
    privilege = custom_claims.get(AUTH_ENVIRONMENT, 0)

    logger.debug(f"extract_user_privilege: customClaims={custom_claims}, environment={AUTH_ENVIRONMENT}, privilege={privilege}")

    return privilege


def check_judge_permission(user_data):
    """Check if user has sufficient privileges to judge (role >= MIN_JUDGE_ROLE)."""
    privilege = extract_user_privilege(user_data)
    return privilege >= MIN_JUDGE_ROLE


def check_admin_permission(user_data):
    """Check if user has admin privileges (role >= MIN_ADMIN_ROLE)."""
    privilege = extract_user_privilege(user_data)
    return privilege >= MIN_ADMIN_ROLE


def get_role_description(privilege):
    """Map privilege level to human-readable role name."""
    role_names = {
        0: 'User',
        1: 'Hacker',
        2: 'Organizer',
        3: 'Executive',
        4: 'Admin'
    }
    return role_names.get(privilege, f'Role Level {privilege}')


def sync_annotator_from_auth_server(user_data):
    """Create or update Gavel annotator from Firebase user data."""
    email = user_data.get('email')
    uid = user_data.get('uid')

    if not email:
        return None

    # Get privilege level and role description
    privilege = extract_user_privilege(user_data)
    role_description = get_role_description(privilege)

    # Find existing annotator by email or Firebase UID
    annotator = Annotator.by_firebase_uid(uid) if uid else None
    if not annotator:
        annotator = Annotator.by_email(email)

    if not annotator:
        # Create new annotator
        annotator = Annotator(
            name=user_data.get('displayName', email.split('@')[0]),
            email=email,
            description=role_description
        )
        annotator.firebase_uid = uid
        annotator.privilege_level = privilege
        # Set active status based on privilege level
        annotator.active = privilege >= MIN_JUDGE_ROLE
        db.session.add(annotator)
        db.session.commit()
    else:
        # Update existing annotator info
        annotator.name = user_data.get('displayName', annotator.name)
        annotator.description = role_description
        if uid and not annotator.firebase_uid:
            annotator.firebase_uid = uid
        annotator.privilege_level = privilege
        # Keep them active if they have sufficient permission level
        annotator.active = privilege >= MIN_JUDGE_ROLE
        db.session.commit()

    return annotator


def hackpsu_auth_required(f):
    """Decorator requiring HackPSU authentication with judge permissions."""
    @wraps(f)
    def decorated(*args, **kwargs):
        logger.debug(f"hackpsu_auth_required: checking auth for {request.path}")

        # Verify Firebase session
        user_data = verify_hackpsu_session()

        if not user_data:
            logger.info(f"hackpsu_auth_required: No valid session, redirecting to login")
            # Redirect to auth flow with return URL
            redirect_url = f'{AUTH_LOGIN_URL}?returnTo={request.url}'
            return redirect(redirect_url)

        logger.debug(f"hackpsu_auth_required: User authenticated as {user_data.get('email')}")

        # Check if user has sufficient privileges
        if not check_judge_permission(user_data):
            privilege = extract_user_privilege(user_data)
            logger.warning(f"hackpsu_auth_required: Insufficient privileges. Has {privilege}, needs {MIN_JUDGE_ROLE}")
            return render_template(
                'error.html',
                message=f'You need organizer permissions (level {MIN_JUDGE_ROLE}+) to access judging. Your current level: {privilege}'
            ), 403

        logger.debug(f"hackpsu_auth_required: Privilege check passed")

        # Get or create Gavel annotator
        annotator = sync_annotator_from_auth_server(user_data)

        if not annotator or not annotator.active:
            logger.warning(f"hackpsu_auth_required: Annotator not found or not active")
            return render_template(
                'error.html',
                message='Your judging account is not active. Please contact an admin.'
            ), 403

        logger.info(f"hackpsu_auth_required: Auth successful for {user_data.get('email')} (annotator_id={annotator.id})")

        # Set Gavel session
        session['annotator_id'] = annotator.id

        return f(*args, **kwargs)
    return decorated


def hackpsu_admin_required(f):
    """Decorator requiring HackPSU authentication with admin permissions."""
    @wraps(f)
    def decorated(*args, **kwargs):
        logger.debug(f"hackpsu_admin_required: checking auth for {request.path}")

        user_data = verify_hackpsu_session()

        if not user_data:
            logger.info(f"hackpsu_admin_required: No valid session, redirecting to login")
            redirect_url = f'{AUTH_LOGIN_URL}?returnTo={request.url}'
            return redirect(redirect_url)

        logger.debug(f"hackpsu_admin_required: User authenticated as {user_data.get('email')}")

        # Check admin permissions
        if not check_admin_permission(user_data):
            privilege = extract_user_privilege(user_data)
            logger.warning(f"hackpsu_admin_required: Insufficient privileges. Has {privilege}, needs {MIN_ADMIN_ROLE}")
            return render_template(
                'error.html',
                message=f'Admin access required. You need permission level {MIN_ADMIN_ROLE}+. Your current level: {privilege}'
            ), 403

        logger.info(f"hackpsu_admin_required: Admin auth successful for {user_data.get('email')}")

        # Still sync annotator for admin (in case they judge too)
        annotator = sync_annotator_from_auth_server(user_data)
        if annotator:
            session['annotator_id'] = annotator.id

        return f(*args, **kwargs)
    return decorated


def get_current_firebase_user():
    """Get the current Firebase user data if authenticated."""
    return verify_hackpsu_session()


def get_session_token():
    """Get the raw session token for API calls."""
    return request.cookies.get('__session')


# Token cache for ID tokens (keyed by user UID)
_id_token_cache = {}


def _exchange_custom_token_for_id_token(custom_token):
    """Exchange a Firebase custom token for an ID token using Firebase REST API.

    Args:
        custom_token: Firebase custom token from Admin SDK

    Returns:
        tuple: (id_token, expires_in_seconds) or (None, 0) on failure
    """
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={FIREBASE_API_KEY}"

    try:
        logger.debug("Exchanging custom token for ID token via Firebase REST API...")
        response = requests.post(
            url,
            json={
                "token": custom_token,
                "returnSecureToken": True
            },
            timeout=10
        )

        if response.status_code != 200:
            logger.error(f"Firebase token exchange failed: {response.status_code} - {response.text}")
            return None, 0

        data = response.json()
        id_token = data.get('idToken')
        expires_in = int(data.get('expiresIn', 3600))

        if id_token:
            logger.info(f"Successfully obtained ID token (expires in {expires_in}s)")
            return id_token, expires_in

        logger.error(f"No idToken in response: {data}")
        return None, 0

    except requests.exceptions.RequestException as e:
        logger.error(f"Firebase token exchange request failed: {e}")
        return None, 0


def _get_id_token_for_user(uid, custom_claims=None):
    """Generate an ID token for a user using Firebase Admin SDK.

    Args:
        uid: Firebase user UID
        custom_claims: Optional custom claims to include

    Returns:
        ID token string or None
    """
    if firebase_auth is None:
        logger.warning("Firebase Admin SDK not available for token generation")
        return None

    if not firebase_has_service_account:
        logger.warning(
            "Firebase Admin SDK does not have a service account configured. "
            "Cannot create custom tokens for ID token generation. "
            "Please add firebase-service-account.json to enable API sync."
        )
        return None

    # Check cache first
    cache_key = uid
    cached = _id_token_cache.get(cache_key)
    if cached:
        token, expiry_time = cached
        if time.time() < expiry_time - 60:  # 60 second buffer before expiry
            logger.debug(f"Using cached ID token for {uid}")
            return token

    try:
        # Create custom token with Admin SDK
        logger.debug(f"Creating custom token for user {uid}...")

        # Include custom claims if provided
        additional_claims = None
        if custom_claims:
            additional_claims = {
                'production': custom_claims.get('production', 0),
                'staging': custom_claims.get('staging', 0)
            }

        custom_token = firebase_auth.create_custom_token(uid, additional_claims)

        # Handle bytes vs string (Firebase Admin SDK may return bytes)
        if isinstance(custom_token, bytes):
            custom_token = custom_token.decode('utf-8')

        logger.debug(f"Custom token created, length={len(custom_token)}")

        # Exchange for ID token
        id_token, expires_in = _exchange_custom_token_for_id_token(custom_token)

        if id_token:
            # Cache the token
            expiry_time = time.time() + expires_in
            _id_token_cache[cache_key] = (id_token, expiry_time)
            logger.info(f"ID token cached for {uid}, expires at {expiry_time}")
            return id_token

        return None

    except Exception as e:
        logger.error(f"Failed to generate ID token for {uid}: {type(e).__name__}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def get_id_token_for_api(session_token=None):
    """Get a Firebase ID token suitable for API calls.

    The HackPSU API expects a Firebase ID token (from getIdToken()),
    not a session cookie. This function creates and caches ID tokens.

    Args:
        session_token: Optional session cookie token (used to get user info)

    Returns:
        ID token string if available, None otherwise
    """
    # Option 1: Use HACKPSU_SERVICE_TOKEN if explicitly set
    service_token = os.environ.get('HACKPSU_SERVICE_TOKEN')
    if service_token:
        logger.debug("Using HACKPSU_SERVICE_TOKEN for API auth")
        return service_token

    # Option 2: Generate ID token from session cookie using Firebase Admin SDK
    if session_token and firebase_auth is not None:
        # Decode session to get user info
        user_data = decode_session_token(session_token)
        if user_data:
            uid = user_data.get('uid') or user_data.get('user_id') or user_data.get('sub')
            if uid:
                # Get custom claims for the token
                custom_claims = None
                if 'production' in user_data or 'staging' in user_data:
                    custom_claims = {
                        'production': user_data.get('production', 0),
                        'staging': user_data.get('staging', 0)
                    }
                elif 'customClaims' in user_data:
                    custom_claims = user_data.get('customClaims')

                id_token = _get_id_token_for_user(uid, custom_claims)
                if id_token:
                    return id_token

    # Option 3: No token available
    logger.warning(
        "Could not generate ID token for API calls. "
        "Ensure Firebase Admin SDK is properly configured with a service account, "
        "or set HACKPSU_SERVICE_TOKEN environment variable."
    )
    return None


@app.context_processor
def inject_user_data():
    """Make user data available to all templates for identification/tracking."""
    session_token = request.cookies.get('__session')
    if session_token:
        try:
            user_data = decode_session_token(session_token)
            return {
                'user_uid': user_data.get('user_id') or user_data.get('sub'),
                'user_email': user_data.get('email'),
                'user_name': user_data.get('name') or user_data.get('displayName'),
                'user_privilege': extract_user_privilege({
                    'customClaims': {
                        'production': user_data.get('production', 0),
                        'staging': user_data.get('staging', 0)
                    }
                })
            }
        except Exception:
            pass
    return {
        'user_uid': None,
        'user_email': None,
        'user_name': None,
        'user_privilege': 0
    }
