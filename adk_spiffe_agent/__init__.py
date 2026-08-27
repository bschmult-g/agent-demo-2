"""ADK SPIFFE Agent Package."""

from adk_spiffe_agent.auth_manager import (
    create_auth_config,
    extract_user_access_token,
    init_auth_callback,
    get_canonical_auth_provider_name,
    DEFAULT_SCOPES,
)
from adk_spiffe_agent.spiffe_identity import (
    build_spiffe_principal,
    parse_spiffe_principal,
    get_ambient_identity_summary,
    apply_auth_provider_iam_binding_cli,
)
from adk_spiffe_agent.agent import (
    create_demo_agent,
    create_calendar_tool,
    create_profile_tool,
    get_user_calendar_events,
    get_user_profile,
    AGENT_SYSTEM_PROMPT,
)

__all__ = [
    "create_auth_config",
    "extract_user_access_token",
    "init_auth_callback",
    "get_canonical_auth_provider_name",
    "DEFAULT_SCOPES",
    "build_spiffe_principal",
    "parse_spiffe_principal",
    "get_ambient_identity_summary",
    "apply_auth_provider_iam_binding_cli",
    "create_demo_agent",
    "create_calendar_tool",
    "create_profile_tool",
    "get_user_calendar_events",
    "get_user_profile",
    "AGENT_SYSTEM_PROMPT",
]
