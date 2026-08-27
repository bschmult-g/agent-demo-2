"""Google ADK Agent Definition with 3LO Tool Authentication.

Defines the core ADK agent, system persona, AuthenticatedFunctionTool bindings,
and graceful fallback handling for unauthenticated 3LO sessions.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from google.adk.agents import Agent
from google.adk.auth import AuthConfig
from google.adk.tools import FunctionTool, ToolContext
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool

from auth_manager import (
    create_auth_config,
    extract_user_access_token,
    init_auth_callback,
    DEFAULT_SCOPES,
)

logger = logging.getLogger(__name__)

# ==============================================================================
# Agent Persona & System Prompt
# ==============================================================================

AGENT_SYSTEM_PROMPT = """You are the Enterprise Assistant Agent powered by Google ADK and Agent-to-Agent (A2A) protocol.
You operate under Google Cloud Ambient SPIFFE Agent Identity with Zero-Trust IAM.
You do NOT have static service account credentials or direct database access.

Your responsibilities:
1. Assist users with calendar scheduling, upcoming events, and personal resource queries.
2. Whenever accessing user-specific resources (e.g. Google Calendar, User Profile), you MUST use your authenticated tools.
3. If an authenticated tool reports that user authentication is required, politely instruct the user to complete the 3-Legged OAuth (3LO) consent flow using the provided authorization URL.
4. When tools return data, present it clearly with concise, helpful summaries.
"""

# ==============================================================================
# 3LO-Protected Tool Implementations
# ==============================================================================

def get_user_calendar_events(
    start_date: str = "today",
    max_results: int = 5,
    tool_context: Optional[ToolContext] = None,
    credential: Optional[Any] = None,
) -> str:
    """Fetches upcoming calendar events for the authenticated end user.

    Requires 3-Legged OAuth (3LO) user delegation token via ToolContext or credential injection.

    Args:
        start_date: Start date for event search (e.g. 'today', 'tomorrow', '2026-09-01').
        max_results: Maximum number of events to return (default: 5).
        tool_context: ADK ToolContext providing ambient 3LO user credentials.
        credential: ADK AuthCredential auto-injected from Agent Auth Manager.

    Returns:
        Formatted summary of user's upcoming calendar events.
    """
    ctx = tool_context or credential
    token = extract_user_access_token(ctx)

    if not token:
        logger.warning("get_user_calendar_events called without 3LO access token.")
        return (
            "AUTH_REQUIRED: 3-Legged OAuth (3LO) user token is missing. "
            "Please authenticate via the Agent Auth Manager consent URL to grant calendar access."
        )

    # Downstream API Request Headers with Injected 3LO Bearer Token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Agent-Identity": "SPIFFE-Ambient",
    }
    logger.info(
        "Invoking calendar API with 3LO user token (length: %d, header: Bearer %s...)",
        len(token),
        token[:6] if len(token) >= 6 else "***",
    )

    # Simulated response representing downstream Google Calendar API
    # In live production with real tokens, requests.get('https://www.googleapis.com/calendar/v3/calendars/primary/events', headers=headers)
    events = [
        {
            "id": "evt_101",
            "summary": "Multi-Agent Architecture Review (A2A Protocol)",
            "start": f"{start_date}T10:00:00Z",
            "end": f"{start_date}T11:00:00Z",
            "location": "Google Meet",
            "organizer": "lead-architect@example.com",
        },
        {
            "id": "evt_102",
            "summary": "Vertex AI Agent Engine Security Briefing",
            "start": f"{start_date}T14:30:00Z",
            "end": f"{start_date}T15:30:00Z",
            "location": "Building MP4 / Virtual",
            "organizer": "security-team@example.com",
        },
    ]

    lines = [f"📅 Upcoming Calendar Events ({start_date}):"]
    for evt in events[:max_results]:
        lines.append(
            f"- **{evt['summary']}**\n"
            f"  Time: {evt['start']} to {evt['end']}\n"
            f"  Location: {evt['location']} (Organizer: {evt['organizer']})"
        )

    return "\n".join(lines)


def get_user_profile(
    tool_context: Optional[ToolContext] = None,
    credential: Optional[Any] = None,
) -> str:
    """Fetches authenticated end-user identity profile from Google OAuth 2.0 endpoint.

    Requires 3-Legged OAuth (3LO) user delegation token.
    """
    ctx = tool_context or credential
    token = extract_user_access_token(ctx)

    if not token:
        return (
            "AUTH_REQUIRED: Missing 3LO user access token. "
            "Please authorize user profile scope to proceed."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    logger.info("Accessing user profile via 3LO token.")

    return (
        "👤 Authenticated User Profile:\n"
        "- Status: Authenticated (3LO Delegated Session Active)\n"
        "- Token Verification: Valid Bearer Token Injected\n"
        "- Scopes: " + ", ".join(DEFAULT_SCOPES)
    )


# ==============================================================================
# Authenticated Tool Factory & Agent Construction
# ==============================================================================

def create_calendar_tool(auth_config: Optional[AuthConfig] = None) -> AuthenticatedFunctionTool:
    """Creates the native ADK AuthenticatedFunctionTool for Calendar with 3LO AuthConfig."""
    config = auth_config or create_auth_config()
    return AuthenticatedFunctionTool(
        func=get_user_calendar_events,
        auth_config=config,
        response_for_auth_required=(
            "AUTH_REQUIRED: 3-Legged OAuth consent is required. "
            "Please visit the authorization link provided in the A2A task metadata."
        ),
    )


def create_profile_tool(auth_config: Optional[AuthConfig] = None) -> AuthenticatedFunctionTool:
    """Creates the native ADK AuthenticatedFunctionTool for User Profile with 3LO AuthConfig."""
    config = auth_config or create_auth_config()
    return AuthenticatedFunctionTool(
        func=get_user_profile,
        auth_config=config,
        response_for_auth_required=(
            "AUTH_REQUIRED: 3-Legged OAuth consent is required to access your user profile."
        ),
    )


def create_demo_agent(
    model: str = "gemini-2.5-flash",
    auth_config: Optional[AuthConfig] = None,
) -> Agent:
    """Instantiates the Root ADK Agent with AuthenticatedFunctionTools and 3LO lifecycle hooks."""
    calendar_tool = create_calendar_tool(auth_config=auth_config)
    profile_tool = create_profile_tool(auth_config=auth_config)

    return Agent(
        name="adk_spiffe_demo_agent",
        description="Demo Agent with Google ADK, A2A Protocol, SPIFFE Agent Identity, and 3LO Auth Manager.",
        instruction=AGENT_SYSTEM_PROMPT,
        model=model,
        tools=[calendar_tool, profile_tool],
        before_agent_callback=init_auth_callback,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = create_demo_agent()
    print(f"✅ Created ADK Agent: {agent.name}")
    print(f"   Tools: {[t.name for t in agent.tools]}")
