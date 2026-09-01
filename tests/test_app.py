from __future__ import annotations

import pytest

from ai_agent_workflow.app import (
    PASSWORD_DIGESTS,
    _parse_workflow_action,
    _public_process,
    _remember_password_digest,
    _sanitize_state,
    _verify_completed_password_update,
    _verify_password,
)
from ai_agent_workflow.workflow import _password_digest, workflow_status


def test_sanitize_state_removes_human_secrets():
    payload = {
        "mfa_code": "123456",
        "new_password": "Str0ngTestPass!",
        "password": "Str0ngTestPass!",
        "password_digest": "hidden",
        "human_inputs": {"mfa_code": "123456"},
        "nested": [{"new_password": "secret"}, {"safe": "value"}],
    }

    sanitized = _sanitize_state(payload)

    assert "mfa_code" not in sanitized
    assert "new_password" not in sanitized
    assert "password" not in sanitized
    assert "password_digest" not in sanitized
    assert "human_inputs" not in sanitized
    assert sanitized["nested"] == [{}, {"safe": "value"}]


def test_waiting_public_process_hides_finalize():
    state = {"needs_human_input": True}
    process = [
        {"node": "collect_human_verification", "status": "waiting"},
        {"node": "finalize", "status": "needs_input"},
    ]

    assert workflow_status(state) == "needs_input"
    assert _public_process(process, state) == [
        {"node": "collect_human_verification", "status": "waiting"}
    ]


def test_parse_workflow_action_handles_supported_routes():
    assert _parse_workflow_action("/api/workflows/reset-password/start") == (
        "reset-password",
        "start",
    )
    assert _parse_workflow_action("/api/workflows/reset-password/resume?x=1") == (
        "reset-password",
        "resume",
    )
    assert _parse_workflow_action("/api/workflows/reset-password/verify-password") == (
        "reset-password",
        "verify_password",
    )
    assert _parse_workflow_action("/api/workflows/reset-password/missing") is None


def test_password_verification_matches_completed_password_digest():
    PASSWORD_DIGESTS.clear()
    _remember_password_digest(
        {
            "request_id": "req_test",
            "password_reset": True,
            "password_digest": _password_digest("Str0ngTestPass!"),
        }
    )

    assert _verify_password("req_test", "Str0ngTestPass!") is True
    assert _verify_password("req_test", "WrongPassword1") is False


def test_password_verification_requires_completed_update():
    PASSWORD_DIGESTS.clear()

    with pytest.raises(ValueError, match="No completed password update"):
        _verify_password("missing", "Str0ngTestPass!")


def test_completed_password_verification_requires_password_reset_state():
    PASSWORD_DIGESTS.clear()
    _remember_password_digest(
        {
            "request_id": "req_test",
            "password_reset": True,
            "password_digest": _password_digest("Str0ngTestPass!"),
        }
    )

    with pytest.raises(ValueError, match="Workflow has not completed a password update"):
        _verify_completed_password_update(
            {"request_id": "req_test", "password_reset": False},
            "Str0ngTestPass!",
        )
