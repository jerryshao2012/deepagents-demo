from langgraph_sdk import Auth
import os

auth = Auth()

@auth.authenticate
async def authenticate(headers: dict) -> Auth.types.MinimalUserDict:
    """Authenticate requests using an API key.
    
    Supports:
    1. 'x-api-key' or 'X-API-Key' header (recommended)
    2. 'Authorization: Bearer <key>' header
    
    The expected key is read from LANGCHAIN_API_KEY environment variable.
    If LANGCHAIN_API_KEY is not set, it falls back to UPLOAD_API_KEY.
    """
    # 1. Try 'x-api-key' header (LangSmith style)
    api_key_bytes = headers.get(b"x-api-key") or headers.get(b"X-API-Key")
    
    # 2. Try 'Authorization: Bearer' header (Standard style)
    if not api_key_bytes:
        auth_header = headers.get(b"authorization") or headers.get(b"Authorization")
        if auth_header and auth_header.startswith(b"Bearer "):
            api_key_bytes = auth_header[7:]
    
    if not api_key_bytes:
        raise Auth.exceptions.HTTPException(
            status_code=401, 
            detail="Missing API key. Please provide 'x-api-key' or 'Authorization: Bearer' header."
        )
    
    try:
        api_key = api_key_bytes.decode("utf-8")
    except Exception:
        raise Auth.exceptions.HTTPException(
            status_code=401, 
            detail="Invalid API key format."
        )

    # Get expected key from environment
    expected_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("UPLOAD_API_KEY")
    
    if not expected_key:
        raise Auth.exceptions.HTTPException(
            status_code=500, 
            detail="Server configuration error: LANGCHAIN_API_KEY not set."
        )

    if api_key != expected_key:
        raise Auth.exceptions.HTTPException(
            status_code=401, 
            detail="Invalid API key."
        )
    
    # Return user identity
    return {"identity": "admin"}
