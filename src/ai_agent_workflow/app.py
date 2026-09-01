"""Dependency-free web server for listing and starting workflows."""

from __future__ import annotations

import argparse
import hmac
import json
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ai_agent_workflow.registry import get_workflow, list_workflows, resume_workflow, start_workflow
from ai_agent_workflow.workflow import workflow_status

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
SENSITIVE_STATE_KEYS = {"human_inputs", "mfa_code", "new_password", "password", "password_digest"}
PASSWORD_DIGESTS: dict[str, str] = {}
WORKFLOW_ACTIONS = {
    "start": "/start",
    "resume": "/resume",
    "verify_password": "/verify-password",
}


def _sanitize_state(value):
    if isinstance(value, dict):
        return {
            key: _sanitize_state(item)
            for key, item in value.items()
            if key not in SENSITIVE_STATE_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_state(item) for item in value]
    return value


def _public_process(process: object, state: dict[str, object]) -> object:
    public_process = _sanitize_state(process)
    if not state.get("needs_human_input") or not isinstance(public_process, list):
        return public_process
    return [
        event
        for event in public_process
        if not (isinstance(event, dict) and event.get("node") == "finalize")
    ]


def _remember_password_digest(state: dict[str, object]) -> None:
    request_id = str(state.get("request_id", ""))
    password_digest = str(state.get("password_digest", ""))
    if state.get("password_reset") and request_id and password_digest:
        PASSWORD_DIGESTS[request_id] = password_digest


def _verify_password(request_id: str, password: str) -> bool:
    stored_digest = PASSWORD_DIGESTS.get(request_id)
    if not stored_digest:
        raise ValueError("No completed password update is available to verify.")
    provided_digest = sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(stored_digest, provided_digest)


def _verify_completed_password_update(state: dict[str, object], password: str) -> bool:
    if not state.get("password_reset"):
        raise ValueError("Workflow has not completed a password update.")
    return _verify_password(str(state.get("request_id", "")), password)


def _parse_workflow_action(path: str) -> tuple[str, str] | None:
    prefix = "/api/workflows/"
    request_path = urlsplit(path).path
    if not request_path.startswith(prefix):
        return None

    workflow_path = request_path[len(prefix) :]
    for action, suffix in WORKFLOW_ACTIONS.items():
        if workflow_path.endswith(suffix):
            return unquote(workflow_path[: -len(suffix)]), action
    return None


class WorkflowRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for the workflow UI and JSON API."""

    server_version = "AIWorkflowHTTP/0.1"

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path == "/":
            self._serve_static("index.html")
            return
        if request_path == "/api/workflows":
            self._send_json({"workflows": list_workflows()})
            return
        if request_path.startswith("/static/"):
            self._serve_static(unquote(request_path.removeprefix("/static/")))
            return
        self._send_json({"detail": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        action = _parse_workflow_action(self.path)
        if action is None:
            self._send_json({"detail": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        workflow_id, mode = action

        try:
            payload = self._read_json()
            task = str(payload.get("task", "")).strip()
            human_inputs = payload.get("human_inputs", {})
            paused_state = payload.get("state", {})
            if mode == "verify_password":
                if get_workflow(workflow_id) is None:
                    raise KeyError(f"Unknown workflow: {workflow_id}")
                if not isinstance(paused_state, dict):
                    self._send_json(
                        {"detail": "state must be an object"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                password = str(payload.get("password", ""))
                verified = _verify_completed_password_update(paused_state, password)
                self._send_json(
                    {
                        "workflow_id": workflow_id,
                        "verified": verified,
                        "message": (
                            "Password update verified successfully."
                            if verified
                            else "Password does not match the updated password."
                        ),
                    }
                )
                return
            if mode == "start" and not task:
                self._send_json({"detail": "Task is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(human_inputs, dict):
                self._send_json(
                    {"detail": "human_inputs must be an object"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            normalized_inputs = {str(key): str(value) for key, value in human_inputs.items()}
            if mode == "start":
                result = start_workflow(
                    workflow_id,
                    task,
                    human_inputs=normalized_inputs,
                )
            else:
                if not isinstance(paused_state, dict):
                    self._send_json(
                        {"detail": "state must be an object"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                result = resume_workflow(
                    workflow_id,
                    paused_state,
                    human_inputs=normalized_inputs,
                )
            state = result.get("state", {})
            if not isinstance(state, dict):
                state = {}
            _remember_password_digest(state)
            public_state = _sanitize_state(state)
            public_process = _public_process(result.get("process", []), state)
        except KeyError as exc:
            self._send_json({"detail": str(exc)}, status=HTTPStatus.NOT_FOUND)
            return
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._send_json({"detail": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json(
            {
                "workflow_id": workflow_id,
                "status": workflow_status(state),
                "public_message": state.get("public_message", ""),
                "final_answer": (
                    "" if state.get("needs_human_input") else state.get("final_answer", "")
                ),
                "state": public_state,
                "process": public_process,
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        parsed = json.loads(raw_body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("Expected a JSON object")
        return parsed

    def _serve_static(self, relative_path: str) -> None:
        target = (STATIC_DIR / relative_path).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self._send_json({"detail": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self._send_json({"detail": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), WorkflowRequestHandler)
    print(f"Workflow UI running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the workflow web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
