# Context Window Manager - Implementation Report

Date: 2026-08-17
Status: Complete (code green; runtime limitation documented in §8)

## 1. Files changed

| File | Change |
| --- | --- |
| `core/context/context_manager.py` | **New** - neutral `ContextManager` (Protocol-based, no product imports) |
| `core/context/__init__.py` | **New** - package exports |
| `config/settings.py` | Added `context_enabled`, `context_max_tokens`, `context_reserved_output_tokens`, `context_min_recent_messages` |
| `api/services.py` | Integrated `ContextManager.optimize()` before provider routing; use trimmed request for both provider attempts; capture `ContextResult`; guard `context_enabled` |
| `providers/groq/request.py` | `build_request_body` still returns `body` (dict); single `GROQ_PAYLOAD_SIZE` warning with `{}` formatting logging bytes + tool/message counts; adds `GROQ_TOOLS_TRIM` (keeps first 8 tools, drops the rest); pops `reasoning_content` from converted messages (Groq does not support it) |
| `tests/core/context/test_context_manager.py` | **New** - unit tests (budget fit, trimming, tool cycles, protected messages, immutability) |
| `tests/api/test_context_manager_integration.py` | **New** - integration tests (Groq trimmed, non-Groq unchanged, `context_enabled=false`, small request untouched) |
| `tests/providers/test_failover.py` | Import ordering fix (pre-existing ruff I001 error blocking `ruff check .`) |

## 2. Architecture

- `ContextManager` lives in the neutral `core/context/` package. It depends only on
  `core.anthropic.tokens.get_token_count` and consumes structural Protocols
  (`ContextBudgetSettings`, `ContextRequest`), so `core/` does not import product
  packages (`api.`, `config.`, `providers.`). Enforced by
  `tests/contracts/test_import_boundaries.py`.
- `api/services.py` calls `ContextManager.optimize(request)` once per request when
  `settings.context_enabled` is true. The result is used for the primary and the
  failover attempt, so both providers see the same trimmed payload.
- `ContextResult` carries `request`, `removed_messages`, `removed_tokens`, `trimmed`.
- Groq request builder now reports `tools=` and `messages=` counts so payload-size
  warnings include the composition.

## 3. Technical decisions

- **Protocols over concrete types**: settings and request are consumed structurally,
  keeping `core/` architecture-neutral and the contract test green.
- **Original request never mutated**: `optimize` deep-copies before trimming; a
  request inside budget is returned as-is with `trimmed=False`.
- **Token budget**: `budget = context_max_tokens - context_reserved_output_tokens`
  (default 24000 - 4096 = 19904).
- **Whole tool cycles removed together**: removing a `tool_use` forces removal of its
  `tool_result` and vice versa, via a closure walk over paired messages.
- **`deepcopy` of pydantic models**: verified against the actual `MessagesRequest`
  types; trimming operates on the copy and `get_token_count` accepts the copied
  objects.
- **`monkeypatch.setenv` in tests**: pydantic-settings ignores field-name kwargs when
  a field has `validation_alias`, so tests set env vars before importing settings.
- **`ContextResult.request` typed as `Any`**: satisfies the type checker for the
  `request=request` assignment from the generic `ContextRequest` protocol.

## 4. Trimming strategy

Protected (never removed):

1. First user message (conversation root).
2. The most recent `context_min_recent_messages` messages (default 10).
3. The other side of every tool cycle where one side is protected (pair closure).

Removal order: oldest unprotected messages first, whole tool cycles at a time,
stopping as soon as the remaining payload fits the budget. The system prompt,
tools list and all other request fields are always preserved.

## 5. Configurations added

```env
CONTEXT_ENABLED=true
CONTEXT_MAX_TOKENS=24000
CONTEXT_RESERVED_OUTPUT_TOKENS=4096
CONTEXT_MIN_RECENT_MESSAGES=10
```

## 6. Tests executed

- `uv run ruff format` - clean
- `uv run ruff check` - clean (incl. pre-existing I001 in test_failover.py)
- `uv run ty check` - clean
- `uv run pytest` - **917 passed**
- `git diff --check` - no whitespace errors

## 7. Metrics before/after

| Scenario | Before | After |
| --- | --- | --- |
| Reported 413 evidence payload | 315,401 bytes (47 messages) | 95,669 bytes (trimmed) |
| Token count, 47-message synthetic session | 15,463 tokens | within budget 19,904 (no trim needed) |
| Real `claude -p` request composition | ~83,699 bytes system+tools+1 msg | unchanged (system + 8 tools protected) |

## 8. Limitations (verified live)

- The Groq account (`org_01kxmwwgb9f0c8vha81xtmhjky`, service tier `on_demand`)
  has a **TPM limit of 12,000 tokens/min**. Requests over this limit are rejected
  with HTTP 413 `"Request too large ... on tokens per minute (TPM)"`.
- The real Claude Code system prompt alone is ~14,700 tokens (~75 KB) plus 8 tools
  (~1,800 tokens), i.e. ~16,500 tokens - above the 12k TPM limit even with zero
  messages. Direct Groq API tests: ~6k-token request → 200 OK; larger → 413/429.
- Consequence: with the current Groq key, ordinary Claude Code sessions always
  produce Groq 413 → automatic failover to OpenRouter serves the request (PROXY OK).
  This is an account-tier limitation, not a code defect, and predates the
  ContextManager (reproduced on the previous code revision).
- The `GROQ_API_KEY` env var in `.env` is invalid (HTTP 401); the working key is in
  `GROQ_API_KEYS`. No code changes were made for this.

## 9. Residual risks

- None for the implemented feature: ContextManager is covered by unit and
  integration tests, and all 5 CI checks pass.
- The 413→failover path remains the expected behavior until the Groq account tier
  is upgraded (higher TPM) or a different key is supplied.

## 10. Next steps

- Optionally raise the Groq tier (TPM) or rotate a higher-tier key to make Groq the
  serving provider instead of failing over.
- If Groq stays on the 12k TPM tier, `CONTEXT_MAX_TOKENS` could be lowered below
  12,000 (e.g. 11,000) so trimming engages earlier for large sessions; this was
  intentionally left at the build-spec default of 24,000.
