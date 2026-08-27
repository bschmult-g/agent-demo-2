#!/usr/bin/env python3
"""End-to-End Verification Test Script for ADK A2A SPIFFE Agent.

Tests:
1. Agent Card discovery (/.well-known/agent-card.json)
2. Health & SPIFFE Identity verification (/healthz)
3. Unauthenticated A2A message -> Graceful 3LO Auth Challenge (AUTH_REQUIRED)
4. Authenticated A2A message with 3LO token -> Tool execution & calendar output
5. Authenticated A2A message with 3LO token -> User profile verification
"""

import asyncio
import logging
import sys
from typing import Any, Dict

import httpx
from dotenv import load_dotenv

load_dotenv()

from a2a_service import A2AService
from spiffe_identity import get_ambient_identity_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("client-test")


async def run_verification_suite(base_url: str = "http://127.0.0.1:8000", use_asgi: bool = True):
    print("==================================================================")
    print("🧪 RUNNING ADK A2A SPIFFE AGENT VERIFICATION SUITE")
    print("==================================================================")

    service = A2AService(host="127.0.0.1", port=8000)
    app = service.app

    async def get_client():
        if use_asgi:
            transport = httpx.ASGITransport(app=app)
            return httpx.AsyncClient(transport=transport, base_url=base_url)
        return httpx.AsyncClient(base_url=base_url)

    # Lifespan context ensures routes from ADK to_a2a are fully mounted
    async with app.router.lifespan_context(app):
        async with await get_client() as client:
            passed = 0
            total = 5

            # -------------------------------------------------------------
            # TEST 1: Agent Card Discovery
            # -------------------------------------------------------------
            print("\n🔍 [TEST 1/5] Testing A2A Agent Card Discovery...")
            res1 = await client.get("/.well-known/agent-card.json")
            if res1.status_code == 200:
                card = res1.json()
                print(f"   ✅ Received Agent Card: {card.get('name')} (v{card.get('version')})")
                print(f"      Protocol: {card.get('protocolVersion')}")
                print(f"      Skills: {[s.get('name') for s in card.get('skills', [])]}")
                passed += 1
            else:
                print(f"   ❌ Failed to get Agent Card: status {res1.status_code} ({res1.text})")

            # -------------------------------------------------------------
            # TEST 2: Healthz & SPIFFE Identity Verification
            # -------------------------------------------------------------
            print("\n🔒 [TEST 2/5] Testing /healthz and Ambient SPIFFE Identity...")
            res2 = await client.get("/healthz")
            if res2.status_code == 200:
                health = res2.json()
                ident = health.get("identity", {})
                print(f"   ✅ Server Health: {health.get('status')}")
                print(f"      Identity Type: {ident.get('identity_type')}")
                print(f"      SPIFFE Principal: {ident.get('spiffe_principal')}")
                print(f"      Target Auth Provider: {ident.get('target_auth_provider')}")
                passed += 1
            else:
                print(f"   ❌ Health check failed: {res2.status_code}")

            # -------------------------------------------------------------
            # TEST 3: Unauthenticated 3LO Tool Request (Auth Challenge Fallback)
            # -------------------------------------------------------------
            print("\n🛡️ [TEST 3/5] Testing Unauthenticated 3LO Request Fallback...")
            unauth_payload = {
                "prompt": "Please fetch my upcoming calendar events for today",
            }
            res3 = await client.post("/a2a/v1/message", json=unauth_payload)
            if res3.status_code == 200:
                data3 = res3.json()
                status_info = data3.get("status", {})
                msg_text = status_info.get("message", {}).get("parts", [{}])[0].get("text", "")
                is_auth_req = status_info.get("authRequired", False) or "Authentication Required" in msg_text or "AUTH_REQUIRED" in msg_text

                if is_auth_req:
                    print(f"   ✅ Graceful 3LO Auth Challenge triggered:")
                    print(f"      State: {status_info.get('state')}")
                    print(f"      Auth Required: {status_info.get('authRequired')}")
                    print(f"      Consent URL: {status_info.get('consentUrl')}")
                    print(f"      Agent Message snippet: {msg_text.splitlines()[0]}")
                    passed += 1
                else:
                    print(f"   ❌ Expected auth challenge, got: {msg_text}")
            else:
                print(f"   ❌ Request failed: {res3.status_code} {res3.text}")

            # -------------------------------------------------------------
            # TEST 4: Authenticated 3LO Tool Request (Token Injection)
            # -------------------------------------------------------------
            print("\n🔑 [TEST 4/5] Testing Authenticated 3LO Calendar Access...")
            mock_3lo_token = "ya29.a0AfH6SM_demo_valid_3lo_oauth_token_calendar_access"
            auth_headers = {"Authorization": f"Bearer {mock_3lo_token}"}
            auth_payload = {
                "prompt": "Check my upcoming calendar events for today",
            }
            res4 = await client.post(
                "/a2a/v1/message",
                json=auth_payload,
                headers=auth_headers,
            )
            if res4.status_code == 200:
                data4 = res4.json()
                status_info4 = data4.get("status", {})
                msg_text4 = status_info4.get("message", {}).get("parts", [{}])[0].get("text", "")

                if "Upcoming Calendar Events" in msg_text4 or "evt_" in msg_text4:
                    print("   ✅ Successfully retrieved calendar events with injected 3LO token:")
                    for line in msg_text4.splitlines()[:5]:
                        print(f"      {line}")
                    passed += 1
                else:
                    print(f"   ❌ Unexpected calendar response: {msg_text4}")
            else:
                print(f"   ❌ Authenticated request failed: {res4.status_code}")

            # -------------------------------------------------------------
            # TEST 5: Authenticated 3LO User Profile Tool Request
            # -------------------------------------------------------------
            print("\n👤 [TEST 5/5] Testing Authenticated 3LO User Profile Access...")
            profile_payload = {
                "prompt": "Show my user profile status",
            }
            res5 = await client.post(
                "/a2a/v1/message",
                json=profile_payload,
                headers=auth_headers,
            )
            if res5.status_code == 200:
                data5 = res5.json()
                status_info5 = data5.get("status", {})
                msg_text5 = status_info5.get("message", {}).get("parts", [{}])[0].get("text", "")

                if "Authenticated User Profile" in msg_text5 or "3LO Delegated Session Active" in msg_text5:
                    print("   ✅ Successfully verified user profile with 3LO delegation:")
                    for line in msg_text5.splitlines():
                        print(f"      {line}")
                    passed += 1
                else:
                    print(f"   ❌ Unexpected profile response: {msg_text5}")
            else:
                print(f"   ❌ Profile request failed: {res5.status_code}")

            # -------------------------------------------------------------
            # Test Summary
            # -------------------------------------------------------------
            print("\n==================================================================")
            print(f"📊 VERIFICATION RESULTS: {passed}/{total} TESTS PASSED")
            if passed == total:
                print("🎉 ALL TESTS PASSED! ADK A2A SPIFFE Agent is fully operational.")
            else:
                print("⚠️ Some tests encountered issues. Please review output above.")
            print("==================================================================")
            return passed == total


def main():
    asyncio.run(run_verification_suite(use_asgi=True))


if __name__ == "__main__":
    main()
