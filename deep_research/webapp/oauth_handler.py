"""OAuth2 authentication with Google and GitHub providers."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from starlette.requests import Request

# OAuth configuration from environment variables
config = Config(
    environ={
        "GOOGLE_CLIENT_ID": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "GOOGLE_CLIENT_SECRET": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "GITHUB_CLIENT_ID": os.environ.get("GITHUB_CLIENT_ID", ""),
        "GITHUB_CLIENT_SECRET": os.environ.get("GITHUB_CLIENT_SECRET", ""),
        "SECRET_KEY": os.environ.get("OAUTH_SECRET_KEY", os.urandom(32).hex()),
    }
)

oauth = OAuth(config)

# Register Google OAuth provider
google = oauth.register(
    name="google",
    client_id=config("GOOGLE_CLIENT_ID"),
    client_secret=config("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Register GitHub OAuth provider
github = oauth.register(
    name="github",
    client_id=config("GITHUB_CLIENT_ID"),
    client_secret=config("GITHUB_CLIENT_SECRET"),
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "user:email"},
)


class OAuthUserManager:
    """Manages OAuth user sessions and token storage."""

    def __init__(self):
        # In production, use Redis or database for session storage
        self.sessions = {}

    def create_session(self, user_data: dict, provider: str) -> str:
        """Create a new session and return session token."""
        import secrets

        session_token = secrets.token_urlsafe(32)
        self.sessions[session_token] = {
            "user_data": user_data,
            "provider": provider,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
        }
        return session_token

    def validate_session(self, session_token: str) -> Optional[dict]:
        """Validate session token and return user data if valid.

        Implements a sliding window: if the session has less than 1 hour
        remaining, automatically extend the expiry by 24 hours from now.
        """
        session = self.sessions.get(session_token)
        if not session:
            return None

        now = datetime.now(timezone.utc)
        if now > session["expires_at"]:
            del self.sessions[session_token]
            return None

        # Sliding window: extend session if less than 1 hour remaining
        remaining = session["expires_at"] - now
        if remaining < timedelta(hours=1):
            session["expires_at"] = now + timedelta(hours=24)

        return session["user_data"]

    def refresh_session(self, session_token: str) -> Optional[dict]:
        """Explicitly extend a session's expiry by 24 hours.

        Returns the user data if the session was found and refreshed,
        None if the session doesn't exist or is already expired.
        """
        session = self.sessions.get(session_token)
        if not session:
            return None

        now = datetime.now(timezone.utc)
        if now > session["expires_at"]:
            del self.sessions[session_token]
            return None

        session["expires_at"] = now + timedelta(hours=24)
        return session["user_data"]

    def cleanup_expired_sessions(self):
        """Remove expired sessions."""
        now = datetime.now(timezone.utc)
        expired = [
            token
            for token, session in self.sessions.items()
            if now > session["expires_at"]
        ]
        for token in expired:
            del self.sessions[token]

    def remove_session(self, session_token: str) -> Optional[str]:
        """Remove a specific session and return the user identity if it existed."""
        session = self.sessions.pop(session_token, None)
        if session:
            return session["user_data"].get("identity")
        return None


# Global user manager instance
user_manager = OAuthUserManager()


async def handle_google_callback(request: Request) -> dict:
    """Handle Google OAuth callback and return user info."""
    try:
        token = await google.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if not userinfo:
            raise Exception("No userinfo found in Google token")

        user_data = {
            "identity": f"google:{userinfo.get('sub')}",
            "email": userinfo.get("email"),
            "name": userinfo.get("name"),
            "picture": userinfo.get("picture"),
            "provider": "google",
            "email_verified": userinfo.get("email_verified", False),
            "locale": userinfo.get("locale"),
            "given_name": userinfo.get("given_name"),
            "family_name": userinfo.get("family_name"),
            "raw_token": token,
        }

        # Create session
        session_token = user_manager.create_session(user_data, "google")
        user_data["session_token"] = session_token

        return user_data

    except Exception as e:
        raise Exception(f"Google OAuth failed: {str(e)}")


async def handle_github_callback(request: Request) -> dict:
    """Handle GitHub OAuth callback and return user info."""
    try:
        token = await github.authorize_access_token(request)

        # Get user info from GitHub API
        resp = await github.get("user", token=token)
        user_info = resp.json()

        # Get user emails
        email_resp = await github.get("user/emails", token=token)
        emails = email_resp.json()

        # Find primary email
        primary_email = next(
            (e["email"] for e in emails if e.get("primary")),
            emails[0]["email"] if emails else None,
        )

        user_data = {
            "identity": f"github:{user_info.get('id')}",
            "username": user_info.get("login"),
            "email": primary_email,
            "name": user_info.get("name") or user_info.get("login"),
            "avatar_url": user_info.get("avatar_url"),
            "provider": "github",
            "bio": user_info.get("bio"),
            "location": user_info.get("location"),
            "company": user_info.get("company"),
            "blog": user_info.get("blog"),
            "followers": user_info.get("followers"),
            "following": user_info.get("following"),
            "public_repos": user_info.get("public_repos"),
            "created_at": user_info.get("created_at"),
            "raw_token": token,
        }

        # Create session
        session_token = user_manager.create_session(user_data, "github")
        user_data["session_token"] = session_token

        return user_data

    except Exception as e:
        raise Exception(f"GitHub OAuth failed: {str(e)}")


async def get_oauth_login_url(request: Request, provider: str, redirect_uri: str) -> str:
    """Generate OAuth login URL for the specified provider."""
    if provider == "google":
        rv = await google.create_authorization_url(redirect_uri=redirect_uri)
        await google.save_authorize_data(request, redirect_uri=redirect_uri, **rv)
        return rv["url"]
    elif provider == "github":
        rv = await github.create_authorization_url(redirect_uri=redirect_uri)
        await github.save_authorize_data(request, redirect_uri=redirect_uri, **rv)
        return rv["url"]
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def handle_logout(session_token: str) -> Optional[str]:
    """Handle user logout by removing session and returning user identity.
    
    Returns the user identity if the session was found and removed, None otherwise.
    The caller (auth.py) should use this identity to clean up _logged_oauth_users.
    """
    identity = user_manager.remove_session(session_token)
    if identity:
        # Also trigger cleanup of any other expired sessions
        user_manager.cleanup_expired_sessions()
    return identity
