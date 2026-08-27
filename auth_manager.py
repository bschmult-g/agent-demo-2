"""Google Cloud Agent Auth Manager - 3-Legged OAuth (3LO) Integration.

Handles 3LO Auth Provider registration, ADK AuthConfig construction,
ambient credential provider registration, and user access token extraction.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.auth import AuthConfig, AuthCredential
from google.adk.auth.credential_manager import CredentialManager
from google.adk.integrations.agent_identity import (
    GcpAuthProvider,
    GcpAuthProviderScheme,
)
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

# Default Environment Variables
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "green-carrier-500109-k2")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
AUTH_PROVIDER_NAME = os.getenv("AUTH_PROVIDER_NAME", "agent-3lo-auth-provider")
CONTINUE_URI = os.getenv(
    "CONTINUE_URI", "https://vertexaisearch.cloud.google.com/oauth-redirect"
)

# 3LO OAuth Credentials
AUTHORIZATION_URL = os.getenv(
    "OAUTH_AUTHORIZATION_URL", "https://accounts.google.com/o/oauth2/v2/auth"
)
TOKEN_URL = os.getenv("OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token")
CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "sample-client-id.apps.googleusercontent.com")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")
DEFAULT_SCOPES: List[str] = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
]


def get_canonical_auth_provider_name(
    provider_name: Optional[str] = None,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Returns the fully qualified GCP resource path for the Auth Provider."""
    target_name = provider_name or AUTH_PROVIDER_NAME
    if target_name.startswith("projects/"):
        return target_name

    proj = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", PROJECT_ID)
    loc = location or os.getenv("GOOGLE_CLOUD_LOCATION", LOCATION)
    if loc == "global":
        loc = "us-central1"

    return f"projects/{proj}/locations/{loc}/authProviders/{target_name}"


def create_authenticated_gcp_auth_provider() -> GcpAuthProvider:
    """Instantiates a GcpAuthProvider configured for ambient Agent Identity."""
    try:
        import google.auth
        from google.cloud.agentidentitycredentials_v1 import (
            AuthProviderCredentialsServiceClient,
        )
        from google.adk.integrations.agent_identity._agent_identity_credentials_provider import (
            _AgentIdentityCredentialsProvider,
        )

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        client = AuthProviderCredentialsServiceClient(credentials=creds)
        agent_id_provider = _AgentIdentityCredentialsProvider(client=client)
        provider = GcpAuthProvider()
        provider._agent_identity_provider = agent_id_provider
        return provider
    except Exception as err:
        logger.debug("Ambient GcpAuthProvider initialization: %s", err)
        return GcpAuthProvider()


# Register the provider locally in ADK's CredentialManager
try:
    CredentialManager.register_auth_provider(create_authenticated_gcp_auth_provider())
except Exception as reg_err:
    logger.debug("CredentialManager register notice: %s", reg_err)


async def init_auth_callback(
    callback_context: Optional[CallbackContext] = None,
) -> None:
    """Callback to guarantee GcpAuthProvider is registered per agent reasoning turn."""
    try:
        provider = create_authenticated_gcp_auth_provider()
        CredentialManager.register_auth_provider(provider)
    except Exception as e:
        logger.debug("init_auth_callback notice: %s", e)


def create_auth_config(
    provider_name: Optional[str] = None,
    scopes: Optional[List[str]] = None,
    continue_uri: Optional[str] = None,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
) -> AuthConfig:
    """Constructs a canonical ADK AuthConfig using GcpAuthProviderScheme for 3LO."""
    canonical_name = get_canonical_auth_provider_name(
        provider_name=provider_name,
        project_id=project_id,
        location=location,
    )

    scheme = GcpAuthProviderScheme(
        name=canonical_name,
        scopes=scopes or DEFAULT_SCOPES,
        continue_uri=continue_uri or CONTINUE_URI,
    )

    return AuthConfig(auth_scheme=scheme)


def extract_user_access_token(
    credential_or_context: Optional[Any] = None,
) -> Optional[str]:
    """Extracts the 3LO OAuth access token from a ToolContext or injected ADK AuthCredential.

    Supports:
    - String token
    - ToolContext auth_token / credentials / state
    - AuthCredential (HttpAuth / OAuth2)
    - Request header dictionary
    """
    if credential_or_context is None:
        return None

    if isinstance(credential_or_context, str):
        return credential_or_context.replace("Bearer ", "").strip()

    # 1. Direct tool_context.auth_token
    if hasattr(credential_or_context, "auth_token") and credential_or_context.auth_token:
        token = extract_user_access_token(credential_or_context.auth_token)
        if token:
            return token

    # 2. Direct tool_context.credentials
    if hasattr(credential_or_context, "credentials") and credential_or_context.credentials:
        token = extract_user_access_token(credential_or_context.credentials)
        if token:
            return token

    # 3. Check session/state for auth response or user token
    if hasattr(credential_or_context, "state") and isinstance(credential_or_context.state, dict):
        state_token = (
            credential_or_context.state.get("auth_token")
            or credential_or_context.state.get("user_token")
            or credential_or_context.state.get("access_token")
        )
        if state_token:
            return str(state_token)

    # 4. Canonical ADK credential structure (HttpAuth)
    if (
        hasattr(credential_or_context, "http")
        and credential_or_context.http
        and hasattr(credential_or_context.http, "credentials")
        and credential_or_context.http.credentials
    ):
        token = getattr(credential_or_context.http.credentials, "token", None)
        if token:
            return token

    # 5. OAuth2 credential structure
    if hasattr(credential_or_context, "oauth2") and credential_or_context.oauth2:
        token = getattr(credential_or_context.oauth2, "access_token", None) or getattr(
            credential_or_context.oauth2, "token", None
        )
        if token:
            return token

    # 6. Dictionary representations
    if isinstance(credential_or_context, dict):
        return (
            credential_or_context.get("access_token")
            or credential_or_context.get("token")
            or credential_or_context.get("http", {}).get("credentials", {}).get("token")
            or credential_or_context.get("credentials")
            or credential_or_context.get("auth_token")
            or credential_or_context.get("user_token")
        )

    return None


def get_auth_provider_registration_payload(
    provider_id: str = AUTH_PROVIDER_NAME,
    authorization_url: str = AUTHORIZATION_URL,
    token_url: str = TOKEN_URL,
    client_id: str = CLIENT_ID,
    client_secret: str = CLIENT_SECRET,
    scopes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generates the GCP Agent Auth Manager provider registration specification."""
    return {
        "authProviderId": provider_id,
        "type": "OAUTH2",
        "oauth2Config": {
            "grantType": "AUTHORIZATION_CODE",
            "authorizationUri": authorization_url,
            "tokenUri": token_url,
            "clientId": client_id,
            "clientSecret": client_secret,
            "scopes": scopes or DEFAULT_SCOPES,
        },
    }
