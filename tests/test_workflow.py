from __future__ import annotations

from ai_agent_workflow.config import Settings
from ai_agent_workflow.workflow import (
    GENERIC_PUBLIC_MESSAGE,
    HUMAN_VERIFICATION_PROMPT,
    build_workflow,
    resume_workflow_process,
    run_agent,
    run_workflow,
    run_workflow_process,
    validate_resumable_state,
    workflow_status,
)


class FakeGateway:
    def complete_json(self, messages):
        system = messages[0]["content"].lower()
        if "validator" in system:
            return {"valid": True, "email": "alex@example.com", "reason": "ok"}
        if "abuse and rate limit" in system:
            return {"allowed": True, "reason": "ok"}
        if "identity service" in system:
            return {"found": True, "account_id": "acct_test", "reason": "ok"}
        if "delivery service" in system:
            return {
                "sent": True,
                "reset_link": "https://example.test/reset-password?token=mock-token-alex-example-com",
                "reason": "ok",
            }
        if "token verifier" in system:
            return {"verified": True, "reason": "ok"}
        if "mfa challenge verifier" in system:
            return {"verified": True, "reason": "ok"}
        if "password policy" in system:
            return {"valid": True, "reason": "ok"}
        if "password update service" in system:
            return {"updated": True, "reason": "ok"}
        if "token revocation" in system:
            return {"revoked": True, "reason": "ok"}
        if "session management" in system:
            return {"invalidated": True, "reason": "ok"}
        if "notification service" in system:
            return {"notified": True, "message": "done"}
        return {}

    def complete(self, messages, *, json_mode=False):
        return "Final test answer"


def test_reset_password_workflow_returns_final_answer():
    graph = build_workflow(lambda: FakeGateway())

    result = graph.invoke(
        {
            "task": "Reset password for alex@example.com",
            "mfa_code": "123456",
            "new_password": "Str0ngTestPass!",
            "step_log": [],
        }
    )

    assert result["final_answer"] == "Final test answer"
    assert result["password_reset"] is True
    assert result["token_revoked"] is True
    assert result["sessions_invalidated"] is True
    assert result["user_notified"] is True


def test_run_agent_uses_mock_gateway():
    result = run_agent(
        "Reset password for alex@example.com",
        settings=Settings(),
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )

    assert "Mock reset password workflow result" in result
    assert "alex@example.com" in result


def test_mock_workflow_success_path_returns_structured_state():
    state = run_workflow(
        "Reset password for alex@example.com",
        settings=Settings(),
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )

    assert state["public_message"] == GENERIC_PUBLIC_MESSAGE
    assert state["user_notified"] is True
    assert state["password_reset"] is True
    assert state["token_revoked"] is True
    assert state["sessions_invalidated"] is True
    assert state["error"] == ""
    assert len(state["step_log"]) == 12
    assert len(state["audit_log"]) == 13


def test_mock_workflow_pauses_for_human_input_after_token_verification():
    state = run_workflow("Reset password for alex@example.com", settings=Settings())

    assert state["needs_human_input"] is True
    assert state["human_prompt"] == HUMAN_VERIFICATION_PROMPT
    assert workflow_status(state) == "needs_input"
    assert state["token_verified"] is True
    assert state["mfa_verified"] is False
    assert state["password_reset"] is False
    assert state["error"] == HUMAN_VERIFICATION_PROMPT
    assert len(state["step_log"]) == 6
    assert state.get("final_answer", "") == ""


def test_mock_workflow_pause_process_does_not_finalize():
    result = run_workflow_process("Reset password for alex@example.com", settings=Settings())

    assert result["state"]["needs_human_input"] is True
    assert result["state"].get("final_answer", "") == ""
    assert [event["node"] for event in result["process"]] == [
        "validate_request",
        "check_rate_limit",
        "lookup_account",
        "send_reset_link",
        "verify_reset_token",
        "collect_human_verification",
    ]


def test_resume_workflow_process_continues_from_human_verification():
    paused = run_workflow("Reset password for alex@example.com", settings=Settings())
    result = resume_workflow_process(
        paused,
        settings=Settings(),
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )

    assert result["state"]["user_notified"] is True
    assert result["state"]["final_answer"]
    assert [event["node"] for event in result["process"]] == [
        "collect_human_verification",
        "verify_mfa_challenge",
        "validate_password_policy",
        "update_password",
        "revoke_reset_token",
        "invalidate_sessions",
        "notify_user",
        "finalize",
    ]
    assert result["process"][0]["message"].startswith("6. Collect human verification: received")


def test_resume_workflow_process_rejects_non_waiting_state():
    state = run_workflow(
        "Reset password for alex@example.com",
        settings=Settings(),
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )

    try:
        resume_workflow_process(
            state,
            settings=Settings(),
            human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
        )
    except ValueError as exc:
        assert str(exc) == "Workflow is not waiting for human input."
    else:
        raise AssertionError("Expected completed workflow state to be rejected")


def test_validate_resumable_state_rejects_pre_token_state():
    try:
        validate_resumable_state({"needs_human_input": True, "token_verified": False})
    except ValueError as exc:
        assert str(exc) == "Workflow cannot resume before reset token verification."
    else:
        raise AssertionError("Expected pre-token workflow state to be rejected")


def test_mock_workflow_process_returns_ordered_langgraph_steps():
    result = run_workflow_process(
        "Reset password for alex@example.com",
        settings=Settings(),
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )
    process = result["process"]

    assert result["state"]["user_notified"] is True
    assert [event["node"] for event in process] == [
        "validate_request",
        "check_rate_limit",
        "lookup_account",
        "send_reset_link",
        "verify_reset_token",
        "collect_human_verification",
        "verify_mfa_challenge",
        "validate_password_policy",
        "update_password",
        "revoke_reset_token",
        "invalidate_sessions",
        "notify_user",
        "finalize",
    ]
    assert process[5]["message"].startswith("6. Collect human verification: received")
    assert process[6]["message"].startswith("7. Verify MFA challenge: verified")


def test_mock_workflow_missing_email_stops_at_validation():
    state = run_workflow("Please help me", settings=Settings())

    assert state["request_valid"] is False
    assert state["public_message"] == "Enter a valid email address."
    assert state["error"] == "No email address was provided."
    assert state["step_log"] == ["1. Validate request: failed (No email address was provided.)"]


def test_mock_workflow_rate_limit_stops_before_account_lookup():
    state = run_workflow("Reset password for alex@rate-limit.test", settings=Settings())

    assert state["rate_limit_allowed"] is False
    assert state["account_found"] is False
    assert state["public_message"] == GENERIC_PUBLIC_MESSAGE
    assert state["error"] == "Too many reset attempts."
    assert len(state["step_log"]) == 2


def test_mock_workflow_missing_account_uses_generic_public_response():
    state = run_workflow("Reset password for alex@missing.test", settings=Settings())

    assert state["account_found"] is False
    assert state["public_message"] == GENERIC_PUBLIC_MESSAGE
    assert state["error"] == "No matching mock account."
    assert len(state["step_log"]) == 3


def test_mock_workflow_delivery_failure_stops_before_token_verification():
    state = run_workflow("Reset password for alex@delivery-fail.test", settings=Settings())

    assert state["reset_link_sent"] is False
    assert state["public_message"] == GENERIC_PUBLIC_MESSAGE
    assert state["error"] == "Mock delivery service rejected the reset email."
    assert len(state["step_log"]) == 4


def test_mock_workflow_expired_token_stops_before_mfa():
    state = run_workflow("Reset password for alex@expired-token.test", settings=Settings())

    assert state["token_verified"] is False
    assert state["mfa_verified"] is False
    assert state["error"] == "Reset token expired."
    assert len(state["step_log"]) == 5


def test_mock_workflow_bad_token_stops_before_mfa():
    state = run_workflow("Reset password for alex@bad-token.test", settings=Settings())

    assert state["token_verified"] is False
    assert state["mfa_verified"] is False
    assert state["password_reset"] is False
    assert state["error"] == "Reset token is missing or invalid."
    assert len(state["step_log"]) == 5


def test_mock_workflow_mfa_failure_stops_before_password_policy():
    state = run_workflow(
        "Reset password for alex@mfa-fail.test",
        settings=Settings(),
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )

    assert state["token_verified"] is True
    assert state["mfa_verified"] is False
    assert state["password_policy_valid"] is False
    assert state["password_reset"] is False
    assert state["error"] == "MFA challenge failed. Use mock code 123456."
    assert len(state["step_log"]) == 7


def test_mock_workflow_wrong_mfa_code_stops_before_password_policy():
    state = run_workflow(
        "Reset password for alex@example.com",
        settings=Settings(),
        human_inputs={"mfa_code": "000000", "new_password": "Str0ngTestPass!"},
    )

    assert state["needs_human_input"] is False
    assert state["token_verified"] is True
    assert state["mfa_verified"] is False
    assert state["password_policy_valid"] is False
    assert state["password_reset"] is False
    assert state["error"] == "MFA challenge failed. Use mock code 123456."
    assert len(state["step_log"]) == 7


# CANDIDATE TASK: add backend-only tests for email, sms, authenticator-app,
# and unsupported MFA challenge types before password policy tests.
def test_mock_workflow_weak_password_stops_before_password_update():
    state = run_workflow(
        "Reset password for alex@weak-password.test",
        settings=Settings(),
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )

    assert state["mfa_verified"] is True
    assert state["password_policy_valid"] is False
    assert state["password_reset"] is False
    assert state["error"] == "Password does not meet policy requirements."
    assert len(state["step_log"]) == 8


def test_mock_workflow_notification_failure_keeps_cleanup_state():
    state = run_workflow(
        "Reset password for alex@notify-fail.test",
        settings=Settings(),
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )

    assert state["password_reset"] is True
    assert state["token_revoked"] is True
    assert state["sessions_invalidated"] is True
    assert state["user_notified"] is False
    assert state["error"] == "Password reset notification was not sent."
    assert len(state["step_log"]) == 12
