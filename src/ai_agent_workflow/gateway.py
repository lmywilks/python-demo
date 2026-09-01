"""Provider-agnostic LLM access with mock and LiteLLM implementations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

Message = dict[str, str]


class Gateway(Protocol):
    """Contract used by the workflow."""

    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str:
        """Return assistant text for a chat completion."""

    def complete_json(self, messages: list[Message]) -> dict[str, Any]:
        """Return parsed JSON for a chat completion."""


@dataclass
class MockLLMGateway:
    """Deterministic gateway for local development, demos, and tests."""

    model: str = "mock/testing-agent"

    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str:
        system = messages[0]["content"].lower()
        user = messages[-1]["content"]

        if json_mode:
            return json.dumps(self.complete_json(messages))
        if "workflow summarizer" in system:
            return self._workflow_summary(user)
        return "Mock gateway response."

    def complete_json(self, messages: list[Message]) -> dict[str, Any]:
        system = messages[0]["content"].lower()
        user = messages[-1]["content"]

        if "password reset request validator" in system:
            email = self._extract_email(user)
            return {
                "valid": bool(email),
                "email": email,
                "reason": "Email found in request." if email else "No email address was provided.",
            }
        if "mock identity service" in system:
            email = self._extract_email(user)
            found = bool(email) and not email.endswith("@missing.test")
            account_hash = sha256(email.encode("utf-8")).hexdigest()[:8]
            return {
                "found": found,
                "account_id": f"acct_{account_hash}" if found else "",
                "reason": "Mock account located." if found else "No matching mock account.",
            }
        if "mock abuse and rate limit service" in system:
            email = self._extract_email(user)
            allowed = bool(email) and not email.endswith("@rate-limit.test")
            return {
                "allowed": allowed,
                "reason": "Request allowed." if allowed else "Too many reset attempts.",
            }
        if "mock password reset delivery service" in system:
            email = self._extract_email(user)
            token = self._token_for(email)
            sent = bool(email) and not email.endswith("@delivery-fail.test")
            reset_link = f"https://example.test/reset-password?token={token}" if sent else ""
            return {
                "sent": sent,
                "reset_link": reset_link,
                "reason": (
                    "Mock reset link sent."
                    if sent
                    else "Mock delivery service rejected the reset email."
                ),
            }
        if "mock reset token verifier" in system:
            verified = "token=mock-token-" in user
            return {
                "verified": verified,
                "reason": self._token_reason(user, verified),
            }
        if "mock mfa challenge verifier" in system:
            # CANDIDATE TASK: make this deterministic verifier respect mfa_challenge_type.
            email = self._extract_email(user)
            code = self._extract_key(user, "mfa_code")
            verified = bool(email) and code == "123456" and not email.endswith("@mfa-fail.test")
            return {
                "verified": verified,
                "reason": (
                    "Mock MFA challenge verified."
                    if verified
                    else "MFA challenge failed. Use mock code 123456."
                ),
            }
        if "mock password policy service" in system:
            email = self._extract_email(user)
            password = self._extract_key(user, "new_password")
            valid = (
                len(password) >= 12
                and any(character.isdigit() for character in password)
                and "weak password" not in user.lower()
                and not email.endswith("@weak-password.test")
            )
            return {
                "valid": valid,
                "reason": (
                    "Password policy passed."
                    if valid
                    else "Password does not meet policy requirements."
                ),
            }
        if "mock password update service" in system:
            updated = (
                "token_verified=True" in user
                and "mfa_verified=True" in user
                and "password_policy_valid=True" in user
            )
            return {
                "updated": updated,
                "reason": (
                    "Mock password record updated."
                    if updated
                    else "Password was not updated because a required security check failed."
                ),
            }
        if "mock token revocation service" in system:
            revoked = "password_reset=True" in user
            return {
                "revoked": revoked,
                "reason": "Reset token revoked." if revoked else "No token was revoked.",
            }
        if "mock session management service" in system:
            invalidated = "password_reset=True" in user
            return {
                "invalidated": invalidated,
                "reason": (
                    "Active sessions invalidated."
                    if invalidated
                    else "No sessions were invalidated."
                ),
            }
        if "mock notification service" in system:
            email = self._extract_email(user)
            notified = (
                "password_reset=True" in user
                and bool(email)
                and not email.endswith("@notify-fail.test")
            )
            return {
                "notified": notified,
                "message": (
                    f"Password reset completed for {email}."
                    if notified
                    else "Password reset notification was not sent."
                ),
            }
        return {}

    def _workflow_summary(self, prompt: str) -> str:
        return "Mock reset password workflow result\n\n" + prompt.strip()

    def _extract_email(self, value: str) -> str:
        match = re.search(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", value)
        return match.group(0).lower() if match else ""

    def _extract_key(self, value: str, key: str) -> str:
        match = re.search(rf"^{re.escape(key)}=(.*)$", value, re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _token_for(self, email: str) -> str:
        if email.endswith("@bad-token.test"):
            return "invalid-token"
        if email.endswith("@expired-token.test"):
            return "expired-token"
        safe_email = re.sub(r"[^a-zA-Z0-9]+", "-", email).strip("-")
        return f"mock-token-{safe_email or 'unknown'}"

    def _token_reason(self, prompt: str, verified: bool) -> str:
        if verified:
            return "Mock token verified."
        if "expired-token" in prompt:
            return "Reset token expired."
        return "Reset token is missing or invalid."


@dataclass
class LiteLLMGateway:
    """LiteLLM wrapper for real provider-backed gateways."""

    model: str
    api_base: str | None = None
    temperature: float = 0.2
    timeout_seconds: int = 60

    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str:
        """Return the assistant text for a chat completion."""

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "timeout": self.timeout_seconds,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        from litellm import completion

        response = completion(**kwargs)
        choice = response.choices[0]
        message = choice["message"] if isinstance(choice, dict) else choice.message
        content = message["content"] if isinstance(message, dict) else message.content
        return content or ""

    def complete_json(self, messages: list[Message]) -> dict[str, Any]:
        """Return parsed JSON from the model, with a helpful error on invalid output."""

        content = self.complete(messages, json_mode=True)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {content}") from exc
        if not isinstance(parsed, dict):
            raise TypeError(f"LLM returned JSON but not an object: {content}")
        return parsed
