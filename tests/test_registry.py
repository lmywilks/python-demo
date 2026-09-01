from __future__ import annotations

from ai_agent_workflow.registry import get_workflow, list_workflows, resume_workflow, start_workflow


def test_list_workflows_exposes_auto_agent():
    workflows = list_workflows()

    assert workflows[0]["id"] == "reset-password"
    assert workflows[0]["name"] == "Reset Password Workflow"


def test_get_workflow_returns_none_for_unknown_id():
    assert get_workflow("missing") is None


def test_start_workflow_returns_structured_state():
    result = start_workflow(
        "reset-password",
        "Reset password for alex@example.com",
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )
    state = result["state"]

    assert state["email"] == "alex@example.com"
    assert state["mfa_verified"] is True
    assert state["user_notified"] is True
    assert result["process"][0]["node"] == "validate_request"
    assert "final_answer" in state


def test_resume_workflow_continues_registered_workflow():
    paused = start_workflow("reset-password", "Reset password for alex@example.com")

    result = resume_workflow(
        "reset-password",
        paused["state"],
        human_inputs={"mfa_code": "123456", "new_password": "Str0ngTestPass!"},
    )

    assert result["process"][0]["node"] == "collect_human_verification"
    assert result["state"]["user_notified"] is True


def test_resume_workflow_rejects_unknown_workflow():
    try:
        resume_workflow("missing", {"needs_human_input": True, "token_verified": True})
    except KeyError as exc:
        assert "Unknown workflow: missing" in str(exc)
    else:
        raise AssertionError("Expected unknown workflow to be rejected")
