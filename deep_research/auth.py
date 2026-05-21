import os

from langgraph_sdk import Auth

from logger_utils import setup_logger
from oauth_handler import user_manager

logger = setup_logger(__name__)

auth = Auth()


@auth.authenticate
async def authenticate(headers: dict) -> Auth.types.MinimalUserDict:
    """Authenticate requests using API key or OAuth session token.
    
    Supports:
    1. 'x-api-key' or 'X-API-Key' header (API key authentication)
    2. 'Authorization: Bearer <key>' header (API key or OAuth session token)
    3. OAuth session tokens from Google/GitHub login
    
    Returns user identity with metadata based on authentication method.
    """
    # Try to get authentication credentials from headers
    api_key_bytes = headers.get(b"x-api-key") or headers.get(b"X-API-Key")

    # Check Authorization header
    if not api_key_bytes:
        auth_header = headers.get(b"authorization") or headers.get(b"Authorization")
        if auth_header and auth_header.startswith(b"Bearer "):
            api_key_bytes = auth_header[7:]

    if not api_key_bytes:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Missing authentication. Please provide 'x-api-key', 'Authorization: Bearer', or OAuth session token."
        )

    try:
        credential = api_key_bytes.decode("utf-8")
    except Exception:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Invalid credential format."
        )

    # First, try to validate as OAuth session token
    user_data = user_manager.validate_session(credential)
    if user_data:
        # OAuth authentication successful - return full user metadata
        identity_ = user_data["identity"]
        logger.info(f"OAuth user data: {user_data}")
        logger.info(f"OAuth authentication successful for provider: {user_data.get('provider')} as {identity_}")
        return {"identity": identity_}

    # If not a valid session token, try API key authentication
    expected_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("UPLOAD_API_KEY")

    if not expected_key:
        raise Auth.exceptions.HTTPException(
            status_code=500,
            detail="Server configuration error: LANGCHAIN_API_KEY not set."
        )

    if credential != expected_key:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Invalid API key or session token."
        )

    # API key authentication successful
    logger.info("API key authentication successful")
    return {"identity": "admin"}
