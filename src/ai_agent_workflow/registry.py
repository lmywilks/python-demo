"""Workflow registry exposed to the API and UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowDefinition:
    """Public metadata and runner for an available workflow."""

    id: str
    name: str
    description: str
    steps: tuple[str, ...]


WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    WorkflowDefinition(
        id="reset-password",
        name="Reset Password Workflow",
        description="Runs a realistic mock password reset with abuse checks, generic public messaging, token and MFA verification, password policy, cleanup, notification, and audit events.",
        steps=(
            "Validate request",
            "Check rate limit",
            "Look up account",
            "Send generic response",
            "Verify token",
            "Collect human verification",
            "Verify MFA",
            "Validate password policy",
            "Update password",
            "Revoke token",
            "Invalidate sessions",
            "Notify user",
            "Finalize",
        ),
    ),
)


def list_workflows() -> list[dict[str, object]]:
    """Return workflow metadata for API responses."""

    return [
        {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "steps": list(workflow.steps),
        }
        for workflow in WORKFLOWS
    ]


def get_workflow(workflow_id: str) -> WorkflowDefinition | None:
    """Look up a workflow by ID."""

    return next((workflow for workflow in WORKFLOWS if workflow.id == workflow_id), None)


def start_workflow(
    workflow_id: str,
    task: str,
    *,
    human_inputs: dict[str, str] | None = None,
) -> dict[str, object]:
    """Start a registered workflow and return state plus process events."""

    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise KeyError(f"Unknown workflow: {workflow_id}")

    from ai_agent_workflow.workflow import run_workflow_process

    return run_workflow_process(task, human_inputs=human_inputs)


def resume_workflow(
    workflow_id: str,
    paused_state: dict[str, object],
    *,
    human_inputs: dict[str, str] | None = None,
) -> dict[str, object]:
    """Resume a registered workflow from a paused state."""

    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise KeyError(f"Unknown workflow: {workflow_id}")

    from ai_agent_workflow.workflow import resume_workflow_process

    return resume_workflow_process(paused_state, human_inputs=human_inputs)
