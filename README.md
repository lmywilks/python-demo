# AI Engineer Testing Project

Python 3.12 project for evaluating AI agent workflow engineering with LangGraph, a mock-first LLM gateway, a small web UI, and deterministic tests.

The implemented workflow is a reset-password agent. It uses the mock gateway by default, so it can run locally without model credentials.

## Features

- LangGraph `StateGraph` workflow with a local fallback runner for setup resilience.
- Mock LLM gateway for deterministic interview and test scenarios.
- Optional LiteLLM gateway for real provider-backed calls.
- Browser UI that lists available workflows and starts the selected workflow.
- Step-by-step process timeline with mock loading states.
- Human-in-the-loop pause for MFA code and new password.
- Final password verification panel that checks the updated password against a server-side digest.
- API response sanitization for MFA codes, new passwords, raw passwords, and password digests.

## Workflow

1. Validate request
2. Check rate limit
3. Look up account
4. Send generic reset response
5. Verify token
6. Collect human verification
7. Verify MFA
8. Validate password policy
9. Update password
10. Revoke token
11. Invalidate sessions
12. Notify user
13. Finalize

If MFA code or new password is missing, the workflow stops at `collect_human_verification` with status `needs_input`. Resume starts from that step; it does not rerun the earlier nodes.

## Setup

Create and activate a Python 3.12 virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

If macOS does not have `python3.12`:

```bash
brew install python@3.12
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

The default environment uses mock mode:

```bash
LLM_GATEWAY=mock
LLM_MODEL=mock/testing-agent
```

To use LiteLLM instead:

```bash
python -m pip install -e ".[dev,real-llm]"
```

Then update `.env`:

```bash
LLM_GATEWAY=litellm
LLM_MODEL=openai/gpt-5-mini
OPENAI_API_KEY=your-key
```

For a LiteLLM proxy or another OpenAI-compatible gateway, also set:

```bash
LLM_API_BASE=https://your-gateway.example.com/v1
```

## Run The Web UI

After installing the package:

```bash
agent-workflow-web
```

Or from the source tree:

```bash
PYTHONPATH=src python -m ai_agent_workflow.app
```

Open:

```text
http://127.0.0.1:8000
```

Enter a task, click `Start Workflow`, wait for the human verification step, then enter:

```text
MFA code: 123456
New password: Str0ngTestPass!
```

After the workflow completes, use the verification panel to confirm the updated password. A wrong password shows an error and a retry button. A correct password shows success and hides the input.

## Run The CLI

Complete workflow:

```bash
agent-workflow "Reset password for alex@example.com" \
  --mfa-code 123456 \
  --new-password "Str0ngTestPass!"
```

Pause at human verification:

```bash
agent-workflow "Reset password for alex@example.com"
```

## API

List workflows:

```http
GET /api/workflows
```

Start a workflow:

```http
POST /api/workflows/reset-password/start
Content-Type: application/json

{
  "task": "Reset password for alex@example.com"
}
```

Resume a paused workflow:

```http
POST /api/workflows/reset-password/resume
Content-Type: application/json

{
  "state": {"needs_human_input": true},
  "human_inputs": {
    "mfa_code": "123456",
    "new_password": "Str0ngTestPass!"
  }
}
```

Verify the completed password update:

```http
POST /api/workflows/reset-password/verify-password
Content-Type: application/json

{
  "state": {"request_id": "req_example", "password_reset": true},
  "password": "Str0ngTestPass!"
}
```

Real API calls must pass the full `state` returned by the previous step. Sensitive values are removed from public responses before state is sent to the browser.

## Mock Inputs

Valid MFA code:

```text
123456
```

Valid password format:

```text
At least 12 characters and at least one number.
```

Example valid password:

```text
Str0ngTestPass!
```

Useful deterministic scenarios:

```text
Reset password for alex@example.com
Please help me
Reset password for alex@rate-limit.test
Reset password for alex@missing.test
Reset password for alex@delivery-fail.test
Reset password for alex@bad-token.test
Reset password for alex@expired-token.test
Reset password for alex@mfa-fail.test
Reset password for alex@weak-password.test
Reset password for alex@notify-fail.test
```

## Test

```bash
pytest
ruff check src tests
ruff format --check src tests
```

## Project Layout

```text
src/ai_agent_workflow/
  app.py        Standard-library web app and API routes
  cli.py        Command-line interface
  config.py     Environment-driven settings
  gateway.py    Mock and LiteLLM gateway implementations
  prompts.py    Prompt templates
  registry.py   Workflow registry
  state.py      LangGraph state schema
  workflow.py   Reset-password workflow graph
  static/       Browser UI
tests/
  test_app.py
  test_registry.py
  test_workflow.py
```

Use [CANDIDATE_TASK.md](CANDIDATE_TASK.md) for candidate instructions and [EVALUATION.md](EVALUATION.md) for reviewer guidance.
