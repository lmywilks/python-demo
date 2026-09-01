# Candidate Task

## Goal

Improve the reset-password AI agent workflow while preserving its current behavior.

The current workflow is:

1. Validate request
2. Check rate limit
3. Look up account internally
4. Send generic reset response
5. Verify token
6. Collect human verification
7. Verify MFA challenge
8. Validate password policy
9. Update password
10. Revoke reset token
11. Invalidate sessions
12. Notify user
13. Finalize

Your task is to add MFA challenge type support:

```text
Support email, SMS, and authenticator-app MFA challenge types.
```

## Requirements

- Preserve the existing LangGraph MFA verification node.
- Preserve the human-in-the-loop pause before MFA verification.
- Route to password update only when MFA verification passes.
- Keep the mock gateway deterministic.
- Add passing and failing tests for at least two MFA challenge types.
- Update the UI/API response so the MFA challenge type appears in the workflow result.
- Keep real LiteLLM usage behind the gateway abstraction.

## Mock Test Cases

Use deterministic inputs so tests do not require real LLM calls:

- `Reset password for alex@example.com` should complete successfully.
- `Reset password for alex@mfa-fail.test` should stop at MFA verification.
- `Reset password for alex@weak-password.test` should stop before password update.

## Notes

- Do not expose or log a real password.
- Do not echo MFA code or new password in API responses.
- Do not call a real email, SMS, or MFA provider.
- Prefer small, focused changes over a broad rewrite.
