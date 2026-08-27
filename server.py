#!/usr/bin/env python3
"""Local A2A Server Runner for ADK SPIFFE Agent.

Launches the local Starlette/Uvicorn server hosting:
- Agent Card Manifest (/.well-known/agent-card.json)
- JSON-RPC 2.0 A2A endpoint (/)
- HTTP REST A2A endpoint (/a2a/v1/message)
- Health check & SPIFFE identity info (/healthz)
"""

import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

from a2a_service import A2AService
from spiffe_identity import get_ambient_identity_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("a2a-server")


def create_app():
    """Application factory for Uvicorn and deployment runtimes."""
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    service = A2AService(host=host, port=port)
    return service.app


app = create_app()


def main():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    identity = get_ambient_identity_summary()

    print("==================================================================")
    print("🚀 STARTING ADK A2A SPIFFE AGENT SERVER")
    print(f"   Host / Port:         http://{host}:{port}")
    print(f"   Identity Type:       {identity['identity_type']}")
    print(f"   SPIFFE Principal:    {identity['spiffe_principal']}")
    print(f"   Auth Provider:       {identity['target_auth_provider']}")
    print(f"   Agent Card URL:      http://{host}:{port}/.well-known/agent-card.json")
    print(f"   HTTP Message URL:    http://{host}:{port}/a2a/v1/message")
    print(f"   JSON-RPC URL:        http://{host}:{port}/")
    print("==================================================================")

    # Security requirement: Server listens on localhost / 127.0.0.1 for testing
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
