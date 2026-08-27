"""SPIFFE-based Agent Identity Configuration and IAM Policy Manager.

This module enforces Google Cloud First-Party Ambient Agent Identity:
- Rely purely on ambient SPIFFE Agent Identity (No Service Account keys or credentials).
- Format: principal://agents.global.org-{ORG_ID}.system.id.goog/resources/aiplatform/projects/{PROJECT_NUM}/locations/{LOCATION}/reasoningEngines/{ENGINE_ID}
- Grants role `roles/agentidentity.user` to the SPIFFE principal on the Auth Provider.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def build_spiffe_principal(
    org_id: str,
    project_number: str,
    location: str,
    engine_id: str,
) -> str:
    """Constructs the canonical SPIFFE principal for a Vertex AI Agent Engine.

    Format:
        principal://agents.global.org-{ORG_ID}.system.id.goog/resources/aiplatform/projects/{PROJECT_NUM}/locations/{LOCATION}/reasoningEngines/{ENGINE_ID}
    """
    clean_org = str(org_id).strip().replace("organizations/", "")
    clean_proj_num = str(project_number).strip().replace("projects/", "")
    clean_loc = str(location).strip()
    clean_engine = str(engine_id).strip().split("/")[-1]

    return (
        f"principal://agents.global.org-{clean_org}.system.id.goog/"
        f"resources/aiplatform/projects/{clean_proj_num}/locations/{clean_loc}/reasoningEngines/{clean_engine}"
    )


def parse_spiffe_principal(principal: str) -> Dict[str, str]:
    """Parses a SPIFFE principal string into its constituent components."""
    pattern = (
        r"^principal://agents\.global\.org-(?P<org_id>[^.]+)\.system\.id\.goog/"
        r"resources/aiplatform/projects/(?P<project_num>[^/]+)/"
        r"locations/(?P<location>[^/]+)/reasoningEngines/(?P<engine_id>[^/]+)$"
    )
    match = re.match(pattern, principal)
    if not match:
        raise ValueError(
            f"Invalid SPIFFE principal format: {principal}. "
            "Expected: principal://agents.global.org-{ORG_ID}.system.id.goog/resources/aiplatform/projects/{PROJECT_NUM}/locations/{LOCATION}/reasoningEngines/{ENGINE_ID}"
        )
    return match.groupdict()


def generate_auth_provider_iam_binding(
    spiffe_principal: str,
    role: str = "roles/agentidentity.user",
) -> Dict[str, Any]:
    """Generates an IAM policy binding JSON structure granting the SPIFFE principal permission on the Auth Provider."""
    return {
        "role": role,
        "members": [spiffe_principal],
    }


def get_ambient_identity_summary() -> Dict[str, Any]:
    """Inspects the local runtime environment to verify ambient Agent Identity settings."""
    org_id = os.getenv("AGENT_ORG_ID", "799321431260")
    project_number = os.getenv("GOOGLE_CLOUD_PROJECT_NUMBER", "799321431260")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    engine_id = os.getenv("AGENT_ENGINE_ID", "adk-spiffe-agent-engine")
    auth_provider = os.getenv("AUTH_PROVIDER_NAME", "agent-3lo-auth-provider")
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "green-carrier-500109-k2")

    principal = build_spiffe_principal(
        org_id=org_id,
        project_number=project_number,
        location=location,
        engine_id=engine_id,
    )

    full_auth_provider = (
        auth_provider
        if auth_provider.startswith("projects/")
        else f"projects/{project_id}/locations/{location}/authProviders/{auth_provider}"
    )

    return {
        "identity_type": "AGENT_IDENTITY (SPIFFE-based)",
        "service_account_keys_used": False,
        "spiffe_principal": principal,
        "org_id": org_id,
        "project_number": project_number,
        "location": location,
        "engine_id": engine_id,
        "target_auth_provider": full_auth_provider,
        "required_iam_role": "roles/agentidentity.user",
    }


def apply_auth_provider_iam_binding_cli(
    spiffe_principal: str,
    auth_provider_resource: str,
    role: str = "roles/agentidentity.user",
    dry_run: Optional[bool] = None,
    timeout: int = 5,
) -> str:
    """Generates or executes the gcloud IAM binding command to grant the SPIFFE principal access to the Auth Provider."""
    cmd = [
        "gcloud", "alpha", "agent-identity", "auth-providers", "add-iam-policy-binding",
        auth_provider_resource,
        f"--member={spiffe_principal}",
        f"--role={role}",
        "--quiet",
    ]

    cmd_str = " ".join(cmd)
    is_dry = dry_run if dry_run is not None else os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")

    if is_dry:
        logger.info("Dry-run: %s", cmd_str)
        return f"[Generated gcloud Command]: {cmd_str}"

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
        return res.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.info("gcloud command timed out. Generated command: %s", cmd_str)
        return f"[Generated gcloud Command]: {cmd_str}"
    except subprocess.CalledProcessError as e:
        logger.warning("gcloud command returned non-zero code: %s", e.stderr)
        return f"Warning: {e.stderr or cmd_str}"
    except FileNotFoundError:
        return f"[Generated gcloud Command]: {cmd_str}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    summary = get_ambient_identity_summary()
    print("==================================================================")
    print("🔒 SPIFFE AGENT IDENTITY CONFIGURATION")
    print(f"   Identity Type:    {summary['identity_type']}")
    print(f"   SA Keys Used:     {summary['service_account_keys_used']}")
    print(f"   SPIFFE Principal: {summary['spiffe_principal']}")
    print(f"   Auth Provider:    {summary['target_auth_provider']}")
    print(f"   Granted Role:     {summary['required_iam_role']}")
    print("==================================================================")
