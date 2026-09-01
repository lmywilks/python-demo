"""Step-by-step reset password workflow for LangGraph."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

try:
    from langgraph.graph import END, START, StateGraph
except ModuleNotFoundError:
    END = "__end__"
    START = "__start__"
    StateGraph = None

from ai_agent_workflow.config import Settings, load_settings
from ai_agent_workflow.gateway import Gateway, LiteLLMGateway, Message, MockLLMGateway
from ai_agent_workflow.prompts import (
    ABUSE_CHECK_SYSTEM,
    ACCOUNT_LOOKUP_SYSTEM,
    FINALIZER_SYSTEM,
    MFA_VERIFIER_SYSTEM,
    NOTIFIER_SYSTEM,
    PASSWORD_POLICY_SYSTEM,
    PASSWORD_UPDATE_SYSTEM,
    RESET_LINK_SYSTEM,
    SESSION_INVALIDATION_SYSTEM,
    TOKEN_REVOCATION_SYSTEM,
    TOKEN_VERIFIER_SYSTEM,
    VALIDATOR_SYSTEM,
)
from ai_agent_workflow.state import AgentState

GatewayFactory = Callable[[], Gateway]
Node = Callable[[AgentState], AgentState]
ProcessEvent = dict[str, object]

GENERIC_PUBLIC_MESSAGE = (
    "If an account exists for that email, password reset instructions have been sent."
)
HUMAN_VERIFICATION_PROMPT = (
    "Enter MFA code and a new password with at least 12 characters and one number."
)


def _messages(system: str, user: str) -> list[Message]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _request_id(task: str) -> str:
    digest = sha256(task.encode("utf-8")).hexdigest()[:12]
    return f"req_{digest}"


def _password_digest(password: str) -> str:
    return sha256(password.encode("utf-8")).hexdigest()


def _append_step(state: AgentState, message: str) -> list[str]:
    return [*state.get("step_log", []), message]


def _audit(state: AgentState, step: str, status: str, reason: str) -> list[dict[str, str]]:
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "request_id": state.get("request_id", ""),
        "step": step,
        "status": status,
        "reason": reason,
    }
    return [*state.get("audit_log", []), event]


def _initial_state_with_inputs(task: str, human_inputs: dict[str, str]) -> AgentState:
    return {
        "task": task,
        "request_id": _request_id(task),
        "human_inputs": human_inputs,
        "email": "",
        "account_id": "",
        "request_valid": False,
        "rate_limit_allowed": False,
        "account_found": False,
        "reset_link_sent": False,
        "reset_link": "",
        "token_verified": False,
        "mfa_verified": False,
        "password_policy_valid": False,
        "password_reset": False,
        "token_revoked": False,
        "sessions_invalidated": False,
        "user_notified": False,
        "notification_message": "",
        "public_message": "",
        "needs_human_input": False,
        "human_prompt": "",
        # CANDIDATE TASK: initialize mfa_challenge_type from deterministic mock inputs.
        "mfa_code": human_inputs.get("mfa_code", ""),
        "new_password": human_inputs.get("new_password", ""),
        "password_digest": "",
        "step_log": [],
        "audit_log": [],
        "error": "",
    }


def _process_event(node_name: str, state: AgentState) -> ProcessEvent:
    latest_step = state.get("step_log", [""])[-1] if state.get("step_log") else ""
    latest_audit = state.get("audit_log", [{}])[-1] if state.get("audit_log") else {}
    if node_name == "finalize":
        latest_step = (
            f"13. Finalize workflow: {latest_audit.get('status', 'completed')} "
            f"({latest_audit.get('reason', 'none')})"
        )
    return {
        "node": node_name,
        "status": latest_audit.get("status", "completed"),
        "message": latest_step or f"{node_name} completed",
        "error": state.get("error", ""),
        "state": dict(state),
    }


def _stream_process(graph, initial_state: AgentState) -> tuple[AgentState, list[ProcessEvent]]:
    current = dict(initial_state)
    process: list[ProcessEvent] = []

    for event in graph.stream(initial_state):
        for node_name, update in event.items():
            if isinstance(update, dict):
                current.update(update)
            process.append(_process_event(node_name, current))

    return current, process


def workflow_status(state: AgentState) -> str:
    """Return the public lifecycle status for a workflow state."""

    if state.get("needs_human_input"):
        return "needs_input"
    if state.get("user_notified"):
        return "completed"
    return "stopped"


def validate_resumable_state(state: AgentState) -> None:
    """Ensure a resume request starts from the expected human-in-the-loop pause."""

    if not state.get("needs_human_input"):
        raise ValueError("Workflow is not waiting for human input.")
    if not state.get("token_verified"):
        raise ValueError("Workflow cannot resume before reset token verification.")
    if state.get("password_reset"):
        raise ValueError("Workflow has already updated the password.")


def build_gateway(settings: Settings | None = None) -> Gateway:
    """Create the configured LLM gateway."""

    settings = settings or load_settings()
    if settings.gateway == "mock":
        return MockLLMGateway(model=settings.model)
    if settings.gateway != "litellm":
        raise ValueError(f"Unsupported LLM_GATEWAY: {settings.gateway}")

    return LiteLLMGateway(
        model=settings.model,
        api_base=settings.api_base,
        temperature=settings.temperature,
        timeout_seconds=settings.timeout_seconds,
    )


def build_workflow(
    gateway_factory: GatewayFactory | None = None,
    *,
    start_node: str = "validate_request",
):
    """Build and compile the reset password LangGraph workflow."""

    gateway_factory = gateway_factory or build_gateway

    def validate_request(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(_messages(VALIDATOR_SYSTEM, state["task"]))
        request_valid = bool(result.get("valid", False))
        email = str(result.get("email", ""))
        reason = str(result.get("reason", ""))
        status = "passed" if request_valid else "failed"
        return {
            "request_valid": request_valid,
            "email": email,
            "error": "" if request_valid else reason,
            "public_message": GENERIC_PUBLIC_MESSAGE
            if request_valid
            else "Enter a valid email address.",
            "step_log": _append_step(state, f"1. Validate request: {status} ({reason})"),
            "audit_log": _audit(state, "validate_request", status, reason),
        }

    def check_rate_limit(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(ABUSE_CHECK_SYSTEM, f"email={state.get('email', '')}")
        )
        allowed = bool(result.get("allowed", False))
        reason = str(result.get("reason", ""))
        status = "passed" if allowed else "blocked"
        return {
            "rate_limit_allowed": allowed,
            "error": "" if allowed else reason,
            "public_message": GENERIC_PUBLIC_MESSAGE,
            "step_log": _append_step(state, f"2. Check rate limit: {status} ({reason})"),
            "audit_log": _audit(state, "check_rate_limit", status, reason),
        }

    def lookup_account(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(ACCOUNT_LOOKUP_SYSTEM, f"email={state.get('email', '')}")
        )
        account_found = bool(result.get("found", False))
        account_id = str(result.get("account_id", ""))
        reason = str(result.get("reason", ""))
        status = "found" if account_found else "not_found"
        return {
            "account_found": account_found,
            "account_id": account_id,
            "error": "" if account_found else reason,
            "public_message": GENERIC_PUBLIC_MESSAGE,
            "step_log": _append_step(
                state,
                f"3. Look up account internally: {status} ({account_id or reason})",
            ),
            "audit_log": _audit(state, "lookup_account", status, reason),
        }

    def send_reset_link(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(RESET_LINK_SYSTEM, f"email={state.get('email', '')}")
        )
        sent = bool(result.get("sent", False))
        reset_link = str(result.get("reset_link", ""))
        reason = str(result.get("reason", ""))
        status = "sent" if sent else "failed"
        return {
            "reset_link_sent": sent,
            "reset_link": reset_link,
            "error": "" if sent else reason,
            "public_message": GENERIC_PUBLIC_MESSAGE,
            "step_log": _append_step(state, f"4. Send generic reset response: {status} ({reason})"),
            "audit_log": _audit(state, "send_reset_link", status, reason),
        }

    def verify_reset_token(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(TOKEN_VERIFIER_SYSTEM, f"reset_link={state.get('reset_link', '')}")
        )
        verified = bool(result.get("verified", False))
        reason = str(result.get("reason", ""))
        status = "verified" if verified else "failed"
        return {
            "token_verified": verified,
            "error": "" if verified else reason,
            "step_log": _append_step(state, f"5. Verify reset token: {status} ({reason})"),
            "audit_log": _audit(state, "verify_reset_token", status, reason),
        }

    def verify_mfa_challenge(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(
                MFA_VERIFIER_SYSTEM,
                f"email={state.get('email', '')}\n"
                f"account_id={state.get('account_id', '')}\n"
                # CANDIDATE TASK: include mfa_challenge_type in this verifier prompt.
                f"mfa_code={state.get('mfa_code', '')}",
            )
        )
        verified = bool(result.get("verified", False))
        reason = str(result.get("reason", ""))
        status = "verified" if verified else "failed"
        return {
            "mfa_verified": verified,
            "error": "" if verified else reason,
            "step_log": _append_step(state, f"7. Verify MFA challenge: {status} ({reason})"),
            "audit_log": _audit(state, "verify_mfa_challenge", status, reason),
        }

    def collect_human_verification(state: AgentState) -> AgentState:
        mfa_code = state.get("mfa_code", "").strip()
        new_password = state.get("new_password", "").strip()
        has_inputs = bool(mfa_code and new_password)
        reason = "Human verification supplied." if has_inputs else HUMAN_VERIFICATION_PROMPT
        status = "received" if has_inputs else "waiting"
        return {
            "needs_human_input": not has_inputs,
            "human_prompt": "" if has_inputs else HUMAN_VERIFICATION_PROMPT,
            "error": "" if has_inputs else reason,
            "public_message": (
                (state.get("public_message") or GENERIC_PUBLIC_MESSAGE)
                if has_inputs
                else "Additional verification is required to continue."
            ),
            "step_log": _append_step(
                state,
                f"6. Collect human verification: {status} ({reason})",
            ),
            "audit_log": _audit(state, "collect_human_verification", status, reason),
        }

    def validate_password_policy(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(
                PASSWORD_POLICY_SYSTEM,
                f"email={state.get('email', '')}\n"
                f"task={state.get('task', '')}\n"
                f"new_password={state.get('new_password', '')}",
            )
        )
        valid = bool(result.get("valid", False))
        reason = str(result.get("reason", ""))
        status = "passed" if valid else "failed"
        return {
            "password_policy_valid": valid,
            "error": "" if valid else reason,
            "step_log": _append_step(state, f"8. Validate password policy: {status} ({reason})"),
            "audit_log": _audit(state, "validate_password_policy", status, reason),
        }

    def update_password(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(
                PASSWORD_UPDATE_SYSTEM,
                f"email={state.get('email', '')}\n"
                f"token_verified={state.get('token_verified')}\n"
                f"mfa_verified={state.get('mfa_verified')}\n"
                f"password_policy_valid={state.get('password_policy_valid')}",
            )
        )
        updated = bool(result.get("updated", False))
        reason = str(result.get("reason", ""))
        status = "updated" if updated else "failed"
        return {
            "password_reset": updated,
            "password_digest": _password_digest(state.get("new_password", "")) if updated else "",
            "error": "" if updated else reason,
            "step_log": _append_step(state, f"9. Update password: {status} ({reason})"),
            "audit_log": _audit(state, "update_password", status, reason),
        }

    def revoke_reset_token(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(TOKEN_REVOCATION_SYSTEM, f"password_reset={state.get('password_reset')}")
        )
        revoked = bool(result.get("revoked", False))
        reason = str(result.get("reason", ""))
        status = "revoked" if revoked else "failed"
        return {
            "token_revoked": revoked,
            "error": "" if revoked else reason,
            "step_log": _append_step(state, f"10. Revoke reset token: {status} ({reason})"),
            "audit_log": _audit(state, "revoke_reset_token", status, reason),
        }

    def invalidate_sessions(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(
                SESSION_INVALIDATION_SYSTEM,
                f"password_reset={state.get('password_reset')}",
            )
        )
        invalidated = bool(result.get("invalidated", False))
        reason = str(result.get("reason", ""))
        status = "invalidated" if invalidated else "failed"
        return {
            "sessions_invalidated": invalidated,
            "error": "" if invalidated else reason,
            "step_log": _append_step(state, f"11. Invalidate sessions: {status} ({reason})"),
            "audit_log": _audit(state, "invalidate_sessions", status, reason),
        }

    def notify_user(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        result = gateway.complete_json(
            _messages(
                NOTIFIER_SYSTEM,
                f"email={state.get('email', '')}\npassword_reset={state.get('password_reset')}",
            )
        )
        notified = bool(result.get("notified", False))
        message = str(result.get("message", ""))
        status = "sent" if notified else "failed"
        return {
            "user_notified": notified,
            "notification_message": message,
            "error": "" if notified else message,
            "step_log": _append_step(state, f"12. Notify user: {status} ({message})"),
            "audit_log": _audit(state, "notify_user", status, message),
        }

    def finalize(state: AgentState) -> AgentState:
        gateway = gateway_factory()
        status = workflow_status(state)
        summary = "\n".join(
            [
                f"Workflow status: {status}",
                f"Request ID: {state.get('request_id')}",
                f"Public response: {state.get('public_message')}",
                f"Needs human input: {state.get('needs_human_input')}",
                f"Human prompt: {state.get('human_prompt') or 'none'}",
                f"Email: {state.get('email') or 'not provided'}",
                f"Account: {state.get('account_id') or 'not found'}",
                f"Reset link: {state.get('reset_link') or 'not generated'}",
                f"Token verified: {state.get('token_verified')}",
                # CANDIDATE TASK: include the selected mfa_challenge_type in the final summary.
                f"MFA verified: {state.get('mfa_verified')}",
                f"Password policy valid: {state.get('password_policy_valid')}",
                f"Password reset: {state.get('password_reset')}",
                f"Token revoked: {state.get('token_revoked')}",
                f"Sessions invalidated: {state.get('sessions_invalidated')}",
                f"Notification: {state.get('notification_message') or 'not sent'}",
                "",
                "Steps:",
                *state.get("step_log", []),
                "",
                f"Stop reason: {state.get('error') or 'none'}",
            ]
        )
        final_answer = gateway.complete(_messages(FINALIZER_SYSTEM, summary))
        return {
            "final_answer": final_answer,
            "audit_log": _audit(state, "finalize", status, state.get("error") or "none"),
        }

    def route_after_validation(state: AgentState) -> str:
        return "check_rate_limit" if state.get("request_valid") else "finalize"

    def route_after_rate_limit(state: AgentState) -> str:
        return "lookup_account" if state.get("rate_limit_allowed") else "finalize"

    def route_after_account_lookup(state: AgentState) -> str:
        return "send_reset_link" if state.get("account_found") else "finalize"

    def route_after_reset_link(state: AgentState) -> str:
        return "verify_reset_token" if state.get("reset_link_sent") else "finalize"

    def route_after_token_verification(state: AgentState) -> str:
        return "collect_human_verification" if state.get("token_verified") else "finalize"

    def route_after_human_verification(state: AgentState) -> str:
        return END if state.get("needs_human_input") else "verify_mfa_challenge"

    def route_after_mfa_verification(state: AgentState) -> str:
        return "validate_password_policy" if state.get("mfa_verified") else "finalize"

    def route_after_password_policy(state: AgentState) -> str:
        return "update_password" if state.get("password_policy_valid") else "finalize"

    def route_after_password_update(state: AgentState) -> str:
        return "revoke_reset_token" if state.get("password_reset") else "finalize"

    def route_after_token_revocation(state: AgentState) -> str:
        return "invalidate_sessions" if state.get("token_revoked") else "finalize"

    def route_after_session_invalidation(state: AgentState) -> str:
        return "notify_user" if state.get("sessions_invalidated") else "finalize"

    nodes: dict[str, Node] = {
        "validate_request": validate_request,
        "check_rate_limit": check_rate_limit,
        "lookup_account": lookup_account,
        "send_reset_link": send_reset_link,
        "verify_reset_token": verify_reset_token,
        "collect_human_verification": collect_human_verification,
        "verify_mfa_challenge": verify_mfa_challenge,
        "validate_password_policy": validate_password_policy,
        "update_password": update_password,
        "revoke_reset_token": revoke_reset_token,
        "invalidate_sessions": invalidate_sessions,
        "notify_user": notify_user,
        "finalize": finalize,
    }
    routes = {
        "validate_request": route_after_validation,
        "check_rate_limit": route_after_rate_limit,
        "lookup_account": route_after_account_lookup,
        "send_reset_link": route_after_reset_link,
        "verify_reset_token": route_after_token_verification,
        "collect_human_verification": route_after_human_verification,
        "verify_mfa_challenge": route_after_mfa_verification,
        "validate_password_policy": route_after_password_policy,
        "update_password": route_after_password_update,
        "revoke_reset_token": route_after_token_revocation,
        "invalidate_sessions": route_after_session_invalidation,
    }

    if StateGraph is None:
        return SimpleWorkflow(nodes=nodes, routes=routes, start_node=start_node)

    builder = StateGraph(AgentState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, start_node)
    for node_name, route in routes.items():
        builder.add_conditional_edges(node_name, route)
    builder.add_edge("notify_user", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()


def run_agent(
    task: str,
    *,
    settings: Settings | None = None,
    human_inputs: dict[str, str] | None = None,
) -> str:
    """Run the reset password workflow for a task and return the final answer."""

    return run_workflow(task, settings=settings, human_inputs=human_inputs).get("final_answer", "")


def run_workflow(
    task: str,
    *,
    settings: Settings | None = None,
    human_inputs: dict[str, str] | None = None,
) -> AgentState:
    """Run the reset password workflow and return the complete state."""

    settings = settings or load_settings()
    graph = build_workflow(lambda: build_gateway(settings))
    result = graph.invoke(_initial_state_with_inputs(task, human_inputs or {}))
    return result


def run_workflow_process(
    task: str,
    *,
    settings: Settings | None = None,
    human_inputs: dict[str, str] | None = None,
) -> dict[str, object]:
    """Run the workflow and return final state plus step-by-step process events."""

    settings = settings or load_settings()
    graph = build_workflow(lambda: build_gateway(settings))
    state, process = _stream_process(graph, _initial_state_with_inputs(task, human_inputs or {}))
    return {"state": state, "process": process}


def resume_workflow_process(
    paused_state: AgentState,
    *,
    settings: Settings | None = None,
    human_inputs: dict[str, str] | None = None,
) -> dict[str, object]:
    """Resume a paused reset password workflow after human verification is supplied."""

    settings = settings or load_settings()
    inputs = human_inputs or {}
    validate_resumable_state(paused_state)
    state: AgentState = {
        **paused_state,
        "human_inputs": inputs,
        # CANDIDATE TASK: preserve or accept mfa_challenge_type when resuming.
        "mfa_code": inputs.get("mfa_code", ""),
        "new_password": inputs.get("new_password", ""),
        "final_answer": "",
    }
    graph = build_workflow(lambda: build_gateway(settings), start_node="collect_human_verification")
    resumed_state, process = _stream_process(graph, state)
    return {"state": resumed_state, "process": process}


class SimpleWorkflow:
    """Fallback runner that mirrors the LangGraph reset password node order."""

    def __init__(
        self,
        *,
        nodes: dict[str, Node],
        routes: dict[str, Callable[[AgentState], str]],
        start_node: str,
    ) -> None:
        self._nodes = nodes
        self._routes = routes
        self._start_node = start_node

    def invoke(self, state: AgentState) -> AgentState:
        current = dict(state)
        node_name = self._start_node

        while True:
            current.update(self._nodes[node_name](current))
            if node_name == "finalize":
                return current
            node_name = self._routes.get(node_name, lambda _: "finalize")(current)
            if node_name == END:
                return current

    def stream(self, state: AgentState):
        current = dict(state)
        node_name = self._start_node

        while True:
            update = self._nodes[node_name](current)
            current.update(update)
            yield {node_name: update}
            if node_name == "finalize":
                return
            node_name = self._routes.get(node_name, lambda _: "finalize")(current)
            if node_name == END:
                return
