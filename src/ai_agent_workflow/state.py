"""LangGraph state schema."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """State passed through the reset password workflow."""

    task: str
    request_id: str
    human_inputs: dict[str, str]
    email: str
    account_id: str
    request_valid: bool
    rate_limit_allowed: bool
    account_found: bool
    reset_link_sent: bool
    reset_link: str
    token_verified: bool
    mfa_verified: bool
    password_policy_valid: bool
    password_reset: bool
    token_revoked: bool
    sessions_invalidated: bool
    user_notified: bool
    notification_message: str
    public_message: str
    needs_human_input: bool
    human_prompt: str
    # CANDIDATE TASK: add mfa_challenge_type here for email, sms, and authenticator-app.
    mfa_code: str
    new_password: str
    password_digest: str
    step_log: list[str]
    audit_log: list[dict[str, Any]]
    error: str
    final_answer: str
