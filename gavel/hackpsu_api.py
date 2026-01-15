# HackPSU API Integration Service
# Handles syncing hackathons and applicants from the HackPSU API

import os
import logging
import requests
from datetime import datetime
from gavel.models import db, Applicant, Hackathon
from gavel import celery
try:
    from gavel.settings import HACKPSU_API_KEY
except ImportError:
    HACKPSU_API_KEY = None

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(levelname)s] %(name)s: %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

# API Configuration
HACKPSU_API_BASE_URL = os.environ.get('HACKPSU_API_BASE_URL', 'https://apiv3.hackpsu.org')
SYNC_INTERVAL_MINUTES = int(os.environ.get('SYNC_INTERVAL_MINUTES', '30'))

logger.info(f"HackPSU API configured: base_url={HACKPSU_API_BASE_URL}")


class HackPSUAPIError(Exception):
    """Exception raised for HackPSU API errors."""
    pass


class HackPSUAPI:
    """Client for the HackPSU API."""

    def __init__(self, base_url=None, api_key=None):
        self.base_url = (base_url or HACKPSU_API_BASE_URL).rstrip('/')
        self.api_key = api_key or HACKPSU_API_KEY

    def _get_auth_header(self, auth_token):
        """Build authorization header."""
        # Prefer API Key if available
        if self.api_key:
            return {'x-api-key': self.api_key}
        
        # Fallback to Bearer token
        if auth_token:
            return {'Authorization': f'Bearer {auth_token}'}
        return {}

    def _get(self, endpoint, params=None, auth_token=None):
        """Make GET request to HackPSU API."""
        url = f"{self.base_url}{endpoint}"
        headers = self._get_auth_header(auth_token)
        headers['Content-Type'] = 'application/json'

        logger.debug(f"API GET request: {url}")
        logger.debug(f"API request params: {params}")
        logger.debug(f"API request has auth token: {bool(auth_token)}")
        if auth_token:
            logger.debug(f"Auth token length: {len(auth_token)}, starts with: {auth_token[:50]}...")

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            logger.debug(f"API response status: {response.status_code}")
            logger.debug(f"API response headers: {dict(response.headers)}")

            if response.status_code != 200:
                logger.error(f"API error response body: {response.text[:500]}")

            response.raise_for_status()
            json_data = response.json()
            logger.debug(f"API response data keys: {list(json_data.keys()) if isinstance(json_data, dict) else 'list'}")
            return json_data
        except requests.exceptions.HTTPError as e:
            logger.error(f"API HTTP error: {e}")
            logger.error(f"Response body: {e.response.text[:500] if e.response else 'No response'}")
            raise HackPSUAPIError(f"API request failed: {str(e)}")
        except requests.exceptions.RequestException as e:
            logger.error(f"API request error: {type(e).__name__}: {e}")
            raise HackPSUAPIError(f"API request failed: {str(e)}")

    def get_hackathons(self, auth_token, active=None):
        """GET /hackathons - Get hackathons, optionally filtered by active status."""
        params = {}
        if active is not None:
            params['active'] = 'true' if active else 'false'
        return self._get('/hackathons', params=params, auth_token=auth_token)

    def get_active_hackathon(self, auth_token):
        """Get the currently active hackathon."""
        logger.info("Fetching active hackathon from API...")
        try:
            data = self.get_hackathons(auth_token, active=True)
            logger.debug(f"get_hackathons returned: {type(data)}")
            logger.debug(f"Response data: {data}")

            # Handle various response formats
            if isinstance(data, dict):
                # Direct hackathon object
                if 'id' in data or 'uid' in data:
                    logger.info(f"Found hackathon directly: {data.get('uid') or data.get('id')}")
                    return data
                # Wrapped in body.data
                if 'body' in data and 'data' in data['body']:
                    result = data['body']['data']
                    logger.debug(f"Unwrapped body.data: {result}")
                    if isinstance(result, list) and len(result) > 0:
                        logger.info(f"Found hackathon in body.data list: {result[0].get('uid', result[0].get('id', 'unknown'))}")
                        return result[0]
                    return result if isinstance(result, dict) else None
                # Wrapped in data
                if 'data' in data:
                    result = data['data']
                    logger.debug(f"Unwrapped data: {result}")
                    if isinstance(result, list) and len(result) > 0:
                        logger.info(f"Found hackathon in data list: {result[0].get('uid', result[0].get('id', 'unknown'))}")
                        return result[0]
                    return result if isinstance(result, dict) else None
            elif isinstance(data, list) and len(data) > 0:
                logger.info(f"Found hackathon in list: {data[0].get('uid', data[0].get('id', 'unknown'))}")
                return data[0]

            logger.warning(f"No active hackathon found in response")
            return None
        except HackPSUAPIError as e:
            logger.error(f"Failed to fetch active hackathon: {e}")
            return None

    def get_users(self, auth_token):
        """GET /users - Get all users."""
        try:
            data = self._get('/users', auth_token=auth_token)
            # Handle various response formats
            if isinstance(data, dict):
                if 'body' in data and 'data' in data['body']:
                    return data['body']['data']
                if 'data' in data:
                    return data['data']
            elif isinstance(data, list):
                return data
            return []
        except HackPSUAPIError:
            return []

    def get_user(self, user_id, auth_token):
        """GET /users/{id} - Get user details."""
        try:
            data = self._get(f'/users/{user_id}', auth_token=auth_token)
            if isinstance(data, dict):
                if 'body' in data and 'data' in data['body']:
                    return data['body']['data']
                if 'data' in data:
                    return data['data']
                if 'id' in data or 'uid' in data:
                    return data
            return None
        except HackPSUAPIError:
            return None

    def get_registrations(self, auth_token, all_registrations=True):
        """GET /registrations - Get all registrations."""
        try:
            params = {'all': 'true'} if all_registrations else {}
            data = self._get('/registrations', params=params, auth_token=auth_token)
            
            # Helper to extract list from response wrappers
            if isinstance(data, dict):
                if 'body' in data and 'data' in data['body']:
                    return data['body']['data']
                if 'data' in data:
                    return data['data']
            elif isinstance(data, list):
                return data
            return []
        except HackPSUAPIError as e:
            logger.error(f"get_registrations failed: {e}")
            return []

    def get_user_info_me(self, auth_token):
        """GET /users/info/me - Get current user's profile with registration."""
        try:
            data = self._get('/users/info/me', auth_token=auth_token)
            if isinstance(data, dict):
                if 'body' in data and 'data' in data['body']:
                    return data['body']['data']
                if 'data' in data:
                    return data['data']
                return data
            return None
        except HackPSUAPIError:
            return None

    def export_users(self, auth_token):
        """GET /users/export - Export users with registration data."""
        try:
            logger.debug(f"Calling /users/export/data with token: {bool(auth_token)}")
            data = self._get('/users/export/data', auth_token=auth_token)
            
            logger.debug(f"export_users response type: {type(data)}")
            if isinstance(data, dict):
                logger.debug(f"export_users dict keys: {list(data.keys())}")
                if 'body' in data and 'data' in data['body']:
                    result = data['body']['data']
                    logger.debug(f"Found {len(result)} users in body.data")
                    return result
                if 'data' in data:
                    result = data['data']
                    logger.debug(f"Found {len(result)} users in data")
                    return result
            elif isinstance(data, list):
                logger.debug(f"Found {len(data)} users in list")
                return data
            
            logger.warning(f"export_users: Could not find user list in response: {data}")
            return []
        except HackPSUAPIError as e:
            logger.error(f"export_users failed: {e}")
            return []


def sync_hackathon(auth_token):
    """Sync active hackathon from HackPSU API.

    Args:
        auth_token: Firebase session token for API authentication

    Returns:
        Hackathon: The synced hackathon object, or None if failed
    """
    logger.info(f"sync_hackathon called with token: {bool(auth_token)}")
    if auth_token:
        logger.debug(f"Token length: {len(auth_token)}")

    api = HackPSUAPI()
    hackathon_data = api.get_active_hackathon(auth_token)

    logger.debug(f"get_active_hackathon returned: {hackathon_data}")

    if not hackathon_data:
        # If we have an API key, getting None likely means no active hackathon or error, 
        # but if we relied on auth_token and it was empty, that's why.
        # However, with API key, auth_token is optional.
        if not auth_token and not HACKPSU_API_KEY:
            logger.error("No auth token and no API Key provided for sync")
            return None
            
        logger.error("No hackathon data returned from API")
        return None

    # Extract hackathon ID (API may use 'id' or 'uid')
    hackathon_id = hackathon_data.get('uid') or hackathon_data.get('id')
    if not hackathon_id:
        return None

    # Check if hackathon exists
    hackathon = Hackathon.by_id(hackathon_id)

    # Parse timestamps if provided
    start_time = None
    end_time = None
    if hackathon_data.get('startTime'):
        try:
            start_time = datetime.fromtimestamp(hackathon_data['startTime'] / 1000)
        except (ValueError, TypeError):
            pass
    if hackathon_data.get('endTime'):
        try:
            end_time = datetime.fromtimestamp(hackathon_data['endTime'] / 1000)
        except (ValueError, TypeError):
            pass

    if not hackathon:
        # Create new hackathon
        hackathon = Hackathon(
            id=hackathon_id,
            name=hackathon_data.get('name', 'HackPSU'),
            start_time=start_time,
            end_time=end_time,
            is_active=True
        )
        db.session.add(hackathon)
    else:
        # Update existing hackathon
        hackathon.name = hackathon_data.get('name', hackathon.name)
        if start_time:
            hackathon.start_time = start_time
        if end_time:
            hackathon.end_time = end_time
        hackathon.is_active = True

    # Deactivate other hackathons
    Hackathon.query.filter(Hackathon.id != hackathon_id).update({'is_active': False})

    hackathon.mark_synced()
    db.session.commit()

    return hackathon


def sync_applicants(hackathon_id, auth_token):
    """Sync all applicants for a hackathon from HackPSU API.

    Args:
        hackathon_id: ID of the hackathon to sync applicants for
        auth_token: Firebase session token for API authentication

    Returns:
        tuple: (synced_count, error_count)
    """
    api = HackPSUAPI()

    # Step 1: Fetch all users
    # We use the basic users endpoint which should be reliable for listing UIDs
    logger.info("Fetching all users...")
    raw_users = api.get_users(auth_token)
    if not isinstance(raw_users, list):
        logger.error(f"Failed to fetch user list. Got: {type(raw_users)}")
        return 0, 0
    
    # Index users by UID for fast lookup
    users_by_id = {}
    for u in raw_users:
        uid = u.get('uid') or u.get('id')
        if uid:
            users_by_id[uid] = u
    
    logger.info(f"Indexed {len(users_by_id)} users")

    # Step 2: Fetch all registrations
    logger.info("Fetching all registrations...")
    registrations = api.get_registrations(auth_token)
    if not isinstance(registrations, list):
        logger.error(f"Failed to fetch registrations. Got: {type(registrations)}")
        return 0, 0
    
    logger.info(f"Fetched {len(registrations)} registrations")

    synced_count = 0
    error_count = 0
    
    # Step 3: Process registrations for the current hackathon
    for reg in registrations:
        try:
            # Check if registration belongs to this hackathon
            reg_hackathon_id = reg.get('hackathonId')
            
            # Handle nested hackathon object if present
            if not reg_hackathon_id and isinstance(reg.get('hackathon'), dict):
                reg_hackathon_id = reg['hackathon'].get('uid') or reg['hackathon'].get('id')
            
            # Skip if not for this hackathon
            # Use string comparison to be safe
            if str(reg_hackathon_id) != str(hackathon_id):
                continue

            # Get the user ID from the registration
            user_id = reg.get('userId')
            if not user_id:
                logger.warning(f"Registration {reg.get('id')} has no userId")
                continue

            # Look up full user details
            user_data = users_by_id.get(user_id)
            if not user_data:
                logger.warning(f"Registration for user {user_id} found, but user details missing from /users list")
                # Optional: Could try to fetch single user here as fallback, but for now just skip
                continue

            # Find or create applicant
            applicant = Applicant.by_hackpsu_id(user_id)

            if not applicant:
                # Create new applicant
                email = user_data.get('email', '')
                if not email:
                    logger.debug(f"Skipping user {user_id}: No email address")
                    continue

                applicant = Applicant(
                    hackpsu_user_id=user_id,
                    email=email,
                    first_name=user_data.get('firstName'),
                    last_name=user_data.get('lastName')
                )
                applicant.hackathon_id = hackathon_id
                db.session.add(applicant)
                logger.info(f"Creating new applicant: {email} ({user_id})")
            
            # Update applicant data merging user profile and registration answers
            # Passing registration object as the second argument which update_from_api expects
            applicant.update_from_api(user_data, reg)
            
            # Ensure hackathon ID is set
            applicant.hackathon_id = hackathon_id
            
            synced_count += 1

        except Exception as e:
            logger.error(f"[ERROR] Failed to process registration {reg.get('id')}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            error_count += 1

    db.session.commit()

    # Update hackathon sync timestamp
    hackathon = Hackathon.by_id(hackathon_id)
    if hackathon:
        hackathon.mark_synced()
        db.session.commit()

    return synced_count, error_count


@celery.task
def periodic_sync_task(service_token=None):
    """Celery task for periodic auto-sync.

    Note: For periodic tasks, we need a service account token since there's
    no user session. This should be configured via environment variable.

    Args:
        service_token: Optional service account token for API auth
    """
    token = service_token or os.environ.get('HACKPSU_SERVICE_TOKEN')

    if not token and not HACKPSU_API_KEY:
        print("[WARN] No service token and no API Key available for periodic sync")
        return

    # Get active hackathon
    hackathon = Hackathon.get_active()
    if not hackathon:
        print("[WARN] No active hackathon for periodic sync")
        return

    # Sync applicants
    # Pass token (may be None if using API Key)
    synced, errors = sync_applicants(hackathon.id, token)
    print(f"[INFO] Periodic sync completed: {synced} synced, {errors} errors")


def setup_periodic_sync(app):
    """Configure Celery beat schedule for periodic sync.

    This should be called during app initialization if auto-sync is desired.
    """
    from celery.schedules import crontab

    # Add periodic task to beat schedule
    app.config['CELERYBEAT_SCHEDULE'] = {
        'sync-applicants': {
            'task': 'gavel.hackpsu_api.periodic_sync_task',
            'schedule': crontab(minute=f'*/{SYNC_INTERVAL_MINUTES}'),
        },
    }
