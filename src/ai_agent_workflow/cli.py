"""Command-line entrypoint for the AI agent workflow."""

from __future__ import annotations

import argparse

from ai_agent_workflow.workflow import run_workflow, workflow_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LangGraph AI agent workflow.")
    parser.add_argument("task", help="Task for the agent to complete.")
    parser.add_argument("--mfa-code", help="Human-provided MFA code for the reset workflow.")
    parser.add_argument(
        "--new-password", help="Human-provided new password for the reset workflow."
    )
    args = parser.parse_args()

    human_inputs = {}
    if args.mfa_code:
        human_inputs["mfa_code"] = args.mfa_code
    if args.new_password:
        human_inputs["new_password"] = args.new_password

    state = run_workflow(args.task, human_inputs=human_inputs)
    final_answer = state.get("final_answer", "")
    if final_answer:
        print(final_answer)
        return

    print(f"Workflow status: {workflow_status(state)}")
    print(f"Public response: {state.get('public_message', '')}")
    if state.get("needs_human_input"):
        print(f"Human input required: {state.get('human_prompt', '')}")
    if state.get("error"):
        print(f"Stop reason: {state['error']}")


if __name__ == "__main__":
    main()
