# Evaluation Guide

Use this project to evaluate practical Python AI agent engineering.

## What Strong Candidates Should Show

- Clear LangGraph node design and routing.
- Deterministic mock gateway behavior.
- Tests for success and failure paths.
- Structured workflow state, not only plain text output.
- Human-in-the-loop handling without leaking sensitive inputs.
- Clean separation between orchestration, gateway, UI/API, and configuration.
- Sensible security thinking for password reset flows.

## Suggested Scoring

- Workflow correctness: 30%
- Test quality: 25%
- Code organization: 20%
- Error handling and edge cases: 15%
- Security awareness: 10%

## Existing Deterministic Scenarios

- `Reset password for alex@example.com`: successful flow.
- `Please help me`: missing email, stops after validation.
- `Reset password for alex@rate-limit.test`: rate limit failure before account lookup.
- `Reset password for alex@missing.test`: account lookup failure.
- `Reset password for alex@delivery-fail.test`: reset link delivery failure.
- `Reset password for alex@bad-token.test`: token verification failure.
- `Reset password for alex@expired-token.test`: expired token failure.
- `Reset password for alex@mfa-fail.test`: MFA verification failure.
- `Reset password for alex@weak-password.test`: password policy failure.
- `Reset password for alex@notify-fail.test`: notification failure after password update.

Use [CANDIDATE_TASK.md](CANDIDATE_TASK.md) as the candidate-facing prompt.
