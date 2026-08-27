"""Agent-to-Agent (A2A) Protocol Service and Client Wrapper.

Implements the A2A Server using ADK `to_a2a`, exposing standard A2A JSON-RPC,
Agent Card discovery (/.well-known/agent-card.json), /healthz, and /a2a/v1/message HTTP endpoints.
Includes a native A2A Client wrapper for task execution and 3LO delegation handling.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent

from agent import create_demo_agent, get_user_calendar_events, get_user_profile
from auth_manager import extract_user_access_token, CONTINUE_URI
from spiffe_identity import get_ambient_identity_summary

logger = logging.getLogger(__name__)


class A2AService:
    """A2A Server exposing standard JSON-RPC, Agent Card, and HTTP task endpoints."""

    def __init__(
        self,
        agent: Optional[Agent] = None,
        host: str = "127.0.0.1",
        port: int = 8000,
        agent_card_path: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.agent = agent or create_demo_agent()

        card_path = agent_card_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "agent_card.json"
        )
        if os.path.exists(card_path):
            with open(card_path, "r", encoding="utf-8") as f:
                self.agent_card_dict = json.load(f)
        else:
            self.agent_card_dict = {"name": self.agent.name, "protocolVersion": "1.0"}

        # Build base A2A Starlette app via ADK
        self.app: Starlette = to_a2a(
            agent=self.agent,
            host=self.host,
            port=self.port,
            protocol="http",
            agent_card=card_path if os.path.exists(card_path) else None,
        )

        # Register supplementary HTTP endpoints for REST/HTTP-JSON A2A interface
        self._register_custom_routes()

    def _register_custom_routes(self) -> None:
        """Adds /healthz and /a2a/v1/message REST endpoints to the Starlette application."""
        async def healthz_endpoint(request: Request) -> Response:
            identity_info = get_ambient_identity_summary()
            return JSONResponse({
                "status": "healthy",
                "service": "adk_spiffe_demo_agent",
                "protocol": "A2A v1.0",
                "identity": identity_info,
                "endpoints": {
                    "agent_card": f"http://{self.host}:{self.port}/.well-known/agent-card.json",
                    "jsonrpc": f"http://{self.host}:{self.port}/",
                    "http_message": f"http://{self.host}:{self.port}/a2a/v1/message",
                },
            })

        async def http_message_endpoint(request: Request) -> Response:
            """Receives incoming A2A message tasks via HTTP/JSON.

            Extracts 3LO token from Authorization header or request payload,
            executes agent reasoning cycle, and returns structured A2A response.
            """
            try:
                payload = await request.json()
            except Exception:
                payload = {}

            # Extract user message prompt
            user_text = ""
            if "prompt" in payload:
                user_text = str(payload["prompt"])
            elif "message" in payload:
                msg = payload["message"]
                parts = msg.get("parts", []) if isinstance(msg, dict) else []
                for p in parts:
                    if isinstance(p, dict) and "text" in p:
                        user_text += p["text"] + " "
                user_text = user_text.strip()
            elif "text" in payload:
                user_text = str(payload["text"])

            if not user_text:
                return JSONResponse(
                    {"error": "Missing user message or prompt in request."},
                    status_code=400,
                )

            session_id = payload.get("session_id", str(uuid.uuid4()))
            task_id = str(uuid.uuid4())

            # Extract 3LO access token
            header_auth = request.headers.get("Authorization")
            auth_token = extract_user_access_token(header_auth) or extract_user_access_token(
                payload.get("auth_token") or payload.get("credentials")
            )

            logger.info("Processing A2A task %s (Session: %s, 3LO Present: %s)", task_id, session_id, bool(auth_token))

            # Simulate/invoke ADK tool reasoning cycle
            # In live reasoning turns, the agent plans tool execution with ToolContext
            lower_text = user_text.lower()
            response_text = ""
            auth_required = False
            consent_url = None

            if "calendar" in lower_text or "event" in lower_text or "schedule" in lower_text:
                if not auth_token:
                    auth_required = True
                    consent_url = f"https://accounts.google.com/o/oauth2/v2/auth?continue={CONTINUE_URI}&client_id=demo"
                    response_text = (
                        "🔒 Authentication Required: Accessing your Google Calendar requires 3-Legged OAuth (3LO) consent.\n"
                        f"Please visit: {consent_url}"
                    )
                else:
                    response_text = get_user_calendar_events(
                        start_date="today",
                        tool_context={"auth_token": auth_token},
                    )
            elif "profile" in lower_text or "who am i" in lower_text or "user" in lower_text:
                if not auth_token:
                    auth_required = True
                    consent_url = f"https://accounts.google.com/o/oauth2/v2/auth?continue={CONTINUE_URI}&client_id=demo"
                    response_text = (
                        "🔒 Authentication Required: Accessing your User Profile requires 3-Legged OAuth (3LO) consent.\n"
                        f"Please visit: {consent_url}"
                    )
                else:
                    response_text = get_user_profile(tool_context={"auth_token": auth_token})
            else:
                response_text = (
                    f"Hello! I am the ADK SPIFFE Agent. I received your request: '{user_text}'. "
                    "I can manage your calendar events and user profile using secure 3LO user delegation."
                )

            # Build standard A2A response structure
            task_state = "input-required" if auth_required else "completed"
            a2a_response = {
                "id": task_id,
                "sessionId": session_id,
                "kind": "task",
                "status": {
                    "state": task_state,
                    "authRequired": auth_required,
                    "consentUrl": consent_url,
                    "message": {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": response_text}],
                    },
                },
                "history": [
                    {
                        "role": "user",
                        "parts": [{"kind": "text", "text": user_text}],
                    },
                    {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": response_text}],
                    },
                ],
                "metadata": {
                    "agent_identity": get_ambient_identity_summary()["spiffe_principal"],
                    "auth_provider": get_ambient_identity_summary()["target_auth_provider"],
                },
            }

            return JSONResponse(a2a_response)

        self.app.routes.append(Route("/healthz", healthz_endpoint, methods=["GET"]))
        self.app.routes.append(Route("/a2a/v1/message", http_message_endpoint, methods=["POST"]))


class A2AClientWrapper:
    """Client wrapper for interacting with A2A agents over HTTP or JSON-RPC."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")

    async def get_agent_card(self) -> Dict[str, Any]:
        """Fetches the Agent Card from the well-known discovery endpoint."""
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            res = await client.get("/.well-known/agent-card.json")
            res.raise_for_status()
            return res.json()

    async def send_message_http(
        self,
        prompt: str,
        auth_token: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends a task message via the /a2a/v1/message HTTP endpoint with optional 3LO Bearer token."""
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        payload = {
            "prompt": prompt,
            "session_id": session_id or str(uuid.uuid4()),
        }

        async with httpx.AsyncClient(base_url=self.base_url) as client:
            res = await client.post(
                "/a2a/v1/message",
                json=payload,
                headers=headers,
                timeout=30.0,
            )
            res.raise_for_status()
            return res.json()

    async def send_message_jsonrpc(
        self,
        prompt: str,
        message_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends a task message via JSON-RPC 2.0 endpoint."""
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        msg_id = message_id or f"msg-{uuid.uuid4()}"
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": msg_id,
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            },
        }

        async with httpx.AsyncClient(base_url=self.base_url) as client:
            res = await client.post("/", json=rpc_payload, headers=headers, timeout=30.0)
            res.raise_for_status()
            return res.json()
