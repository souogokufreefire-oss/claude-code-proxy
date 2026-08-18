# Changelog

## Unreleased

Context Window Manager release.

### Added

- OpenAI chat reasoning and tool history replay, ported from upstream PR #1002
  (commit 0723120): assistant `reasoning_content` — including explicit empty
  strings — is preserved and replayed across turns, and tool history is
  replayed with `tool_use` IDs and ordering intact. User/assistant text after a
  `tool_use` is buffered until the matching `tool_result` sequence completes
  (nested and multi-tool turns included), so every OpenAI chat payload keeps
  valid `tool_calls` → `tool` adjacency. Streaming treats `reasoning_content=""`
  as explicit state: it starts the thinking block without emitting spurious
  deltas. Groq never receives a `reasoning_content` key. The 9 native
  Anthropic-transport providers (DeepSeek, OpenRouter, LM Studio, llama.cpp,
  Ollama, FriendliAI, Fireworks, vLLM, CLIProxyAPI) are unaffected.
- Thinking/reasoning smoke coverage for all 14 providers (commit ef1cf5e):
  smoke model defaults for FriendliAI, Fireworks, vLLM, CLIProxyAPI, Groq,
  Cerebras, Together, and Kimi, with per-provider `FCC_SMOKE_MODEL_*`
  overrides; `has_provider_configuration` covers all 14 providers; new
  product scenarios `test_provider_thinking_emission_e2e` (adaptive thinking
  must emit thinking blocks, retried twice, documented skip otherwise) and
  `test_provider_reasoning_content_roundtrip_e2e` (OpenAI-chat thinking
  providers must survive reasoning_content replay). Together declared
  `thinking` in the provider catalog (request builder replays reasoning via
  `reasoning_content`); Groq remains non-thinking with a documented catalog
  note (reasoning_content keys are stripped before dispatch).
- Context Window Manager (`CONTEXT_*` settings) that trims oversized Groq
  payloads before dispatch: oversized conversations are reduced while
  preserving the system prompt, the first user message, the most recent
  `CONTEXT_MIN_RECENT_MESSAGES` messages, and complete `tool_use` /
  `tool_result` cycles. Implemented as a neutral `core/context/context_manager.py`
  consumed by the service layer, with a budget of
  `CONTEXT_MAX_TOKENS - CONTEXT_RESERVED_OUTPUT_TOKENS`. The trimmed request is
  used for both the primary provider and the failover attempt. Groq-only by
  design; other providers are untouched.
- `CONTEXT_ENABLED`, `CONTEXT_MAX_TOKENS`, `CONTEXT_RESERVED_OUTPUT_TOKENS`,
  `CONTEXT_MIN_RECENT_MESSAGES` settings, documented in `.env.example`.
- Groq request builder diagnostics: single `GROQ_PAYLOAD_SIZE` warning with
  byte, tool, and message counts; `GROQ_TOOLS_TRIM` keeps the first 8 tools;
  `reasoning_content` keys are dropped (unsupported by Groq).
- Unit tests (`tests/core/context/`) and service-level integration tests
  (`tests/api/test_context_manager_integration.py`) — 992 tests total.

### Known Limitation

- The Groq account used during validation is on an `on_demand` tier with a
  TPM limit of 12,000 tokens/min. A real Claude Code request (system prompt
  alone ≈14,700 tokens plus ~1,800 tokens of tools) exceeds that limit before
  any conversation messages are added, so Groq still answers with HTTP 413 and
  the proxy fails over to OpenRouter. This is an account/tier limitation, not
  a code defect; it predates the Context Window Manager and is unaffected by
  it.

## 2.2.0 - 2026-07-08

Kimi provider, upstream compatibility and security hardening release.

### Added

- Kimi / Moonshot provider using OpenAI-compatible chat completions at
  `https://api.moonshot.ai/v1` with bearer authentication. Reasoning history is
  replayed as `reasoning_content` for tool-call turns when thinking is enabled.
  Adapted from upstream PR #335.
- DeepSeek provider improvements: extended `thinking` parameter support and
  Anthropic-side request/response coverage for the OpenAI-compatible
  chat-completions transport.
- Explicit security-floor pins in `pyproject.toml` for transitive deps pulled by
  `fastapi[standard]` (starlette, aiohttp, python-multipart, pydantic-settings)
  so patched versions are always selected and the requirement is explicit.
- Markdown planning foundation: `HANDOFF.md` (repo state, key files, resume
  guide), `ROADMAP.md` (near / mid / long-term direction), and `BACKLOG.md`
  (prioritized work items and completed history).
- GitHub repository auto-merge enabled for dependabot, with a documented
  major-version exclusion policy and a `open-pull-requests-limit` cap on the
  dependabot config to prevent stale PR pileup.
- Local CLI tooling: `Makefile` with `format`, `lint`, `typecheck`, `test`, and
  `test-live` targets, plus `MASK_MACOS_METADATA` plumbing in `.gitignore`.
- Upstream audit log: `UPSTREAM_AUDIT_PLAN.md` captures the 2026-05-09 mining
  pass for future upstream cherry-picks.

### Changed

- Expanded supported provider IDs from thirteen to fourteen with the addition of
  `kimi`. Current set: `nvidia_nim`, `open_router`, `deepseek`, `lmstudio`,
  `llamacpp`, `ollama`, `friendliai`, `fireworks`, `vllm`, `cliproxyapi`,
  `groq`, `cerebras`, `together`, `kimi`.
- Local provider timeouts bumped to 60s connect/write, and default HTTP timeouts
  in `.env.example` raised to 120s to match upstream. `LM_STUDIO_API_KEY` is
  exposed in the proxy `.env` while keeping the unauthenticated lm-studio
  fallback for servers that do not require a key.
- File logging defaults to INFO with DEBUG opt-in, default SSE debug
  serialization removed, and avoidable tool-parser scans skipped when the
  request has no tool use.
- OpenAI-compatible providers use pooled HTTP clients and a chunk-accumulation
  SSE buffer in `EmittedNativeSseTracker` to cut per-chunk allocations and
  avoid quadratic joins on long streams.
- NVIDIA NIM tool-call sanitization now removes unsupported boolean-only
  `items` schemas before dispatch, preventing upstream 400s on synthetic
  schemas generated by Claude Code.
- Live smoke product validation accepts valid thinking-only Anthropic streams
  from local reasoning models such as `qwen3`.
- CI: bumped `astral-sh/setup-uv` to v8.2.0 and pinned `uv` to 0.11.19.

### Fixed

- Read-only filesystem stderr fallback in `config/logging_config.py` so the
  proxy still emits logs when the log file path is unwritable
  (upstream PR #388, AashishKumar-3002).
- `tiktoken.ENCODER.encode()` calls now pass `disallowed_special=()`, preventing
  crashes on disallowed special tokens
  (upstream PR #382, LVT382009).
- Optimization handlers return Anthropic SSE streams instead of raw JSON, so
  Claude Code consumes them correctly
  (upstream PR #383, Klausc06).
- Pre-existing Python 3.14 syntax error in `core/anthropic/tokens.py` corrected
  to `except (TypeError, ValueError)`.

### Security

- `starlette` 0.52.1 → 1.3.1 (3 high, 3 moderate advisories) covering
  `request.form()` DoS limits bypass, SSRF / NTLM credential theft via UNC
  paths on Windows, `request.url.hostname` poisoning, missing Host header
  validation, `HTTPEndpoint` `__getattr__` method dispatch, and `StaticFiles`
  UNC path injection.
- `aiohttp` 3.13.5 → 3.14.1 (2 medium, 6 low advisories) covering websocket
  frame payload memory bypass, TLS hostname override ignored, HTTP/1 pipelined
  request flooding, compressed-body bypass of `client_max_size`, C-parser
  `max_line_size` bypass, DigestAuth cross-origin redirect, host-only cookie
  domain expansion, and CRLF injection in multipart headers.
- `python-multipart` 0.0.27 → 0.0.32 (1 high, 3 low) covering
  quadratic-time querystring parsing DoS, negative `Content-Length`
  full-body buffering, semicolon separator parameter smuggling, and
  `Content-Disposition` RFC 2231 / 5987 smuggling.
- `pydantic-settings` 2.14.0 → 2.14.2 (1 medium) covering
  `NestedSecretsSettingsSource` symlink traversal outside `secrets_dir`.
- Bumped runtime and dev deps via `uv lock` refresh: `fastapi` 0.136 → 0.139,
  `uvicorn` 0.46 → 0.50, `openai` 2.34 → 2.44, `pydantic` 2.13.3 → 2.13.4,
  `ruff` 0.15.12 → 0.15.20, `ty` 0.0.34 → 0.0.56, `rich` 14 → 15, plus
  transitive `idna` 3.11 → 3.15 and `urllib3` 2.6.3 → 2.7.0.

### Verified

- Local CI checks passed: formatting, linting, type checking, and the full unit
  test suite (858 passed).
- Live product smoke scenarios updated to accept thinking-only streams from
  local reasoning models; unconfigured provider targets remain skipped by the
  smoke configuration.

## 2.1.0 - 2026-04-30

Provider expansion release for hosted and local upstream backends.

### Added

- FriendliAI provider using native Anthropic Messages transport with bearer
  authentication and fallback key rotation.
- Fireworks AI provider using native Anthropic Messages transport at the
  `/inference/v1` endpoint with bearer authentication.
- vLLM local provider using native Anthropic Messages transport at the
  configured local `/v1` endpoint.
- CLIProxyAPI local provider for routing through Claude OAuth-backed
  Anthropic-compatible API servers.
- Groq provider using OpenAI-compatible chat completions with Anthropic request
  conversion and streaming SSE translation.
- Cerebras provider using OpenAI-compatible chat completions, including
  retry-without-`reasoning_effort` handling for models that reject that field.
- Together AI provider using OpenAI-compatible chat completions with Anthropic
  request conversion and streaming SSE translation.
- Provider catalog, settings, `.env.example`, README, unit tests, and smoke
  capability metadata for the new providers.

### Changed

- Expanded supported provider IDs from six to thirteen:
  `nvidia_nim`, `open_router`, `deepseek`, `lmstudio`, `llamacpp`, `ollama`,
  `friendliai`, `fireworks`, `vllm`, `cliproxyapi`, `groq`, `cerebras`, and
  `together`.
- Documented provider-specific configuration examples for FriendliAI,
  Fireworks AI, vLLM, CLIProxyAPI, Groq, Cerebras, and Together AI.
- Kept OpenAI-compatible provider request bodies on `max_tokens` for SDK and
  provider compatibility.

### Verified

- Local CI checks passed: formatting, linting, type checking, and the full unit
  test suite.
- Live product smoke coverage passed for configured provider targets against a
  local proxy; unavailable or unconfigured provider targets were skipped by the
  smoke configuration.

## 2.0.0 - 2026-04-29

First `claude-code-proxy` release after narrowing the repository to the proxy
service.

### Added

- Proxy-only package identity: `claude-code-proxy`.
- Installed entry points: `claude-code-proxy` and `ccp-init`.
- Compatibility entry points: `free-claude-code` and `fcc-init`.
- Anthropic-compatible routing for Claude Code CLI, VS Code, and JetBrains ACP.
- Provider routing for NVIDIA NIM, OpenRouter, DeepSeek, LM Studio, llama.cpp,
  and Ollama.
- Per-tier model routing with `MODEL_OPUS`, `MODEL_SONNET`, `MODEL_HAIKU`, and
  fallback `MODEL`.
- Provider fallback key rotation for key-scoped 401/429 failures.
- Request-scoped model override via `ANTHROPIC_AUTH_TOKEN` suffixes.
- Local optimizations for Claude Code probes, title generation, suggestion mode,
  and filepath extraction.
- Optional local handlers for Anthropic `web_search` and `web_fetch` server
  tools.
- OpenAI-compatible user image conversion for Anthropic base64 and URL image
  blocks, adapted from upstream PR #271 / issue #260.
- Release CI enforcing formatting, linting, type checking, tests, and no
  `# type: ignore` / `# ty: ignore` suppressions.

### Changed

- Shared Anthropic protocol helpers now live under `core/anthropic/`.
- Provider metadata is descriptor-driven through `config.provider_catalog`.
- NVIDIA NIM short model names are auto-prefixed for common vendor namespaces,
  adapted from upstream PR #259.
- `ANTHROPIC_AUTH_TOKEN` comparison uses constant-time comparison, adapted from
  upstream PR #262.
- Smoke configuration parsing now reports clear validation errors, adapted from
  upstream PR #264.
- OpenAI-compatible conversion repairs invalid tool message sequences from long
  Claude Code sessions before provider dispatch.
- `claude-pick` fetches current NVIDIA NIM models live instead of relying on a
  committed static model snapshot.

### Removed

- Telegram and bot-specific product surface from the trimmed release scope.
- Stale `nvidia_nim_models.json` model snapshot.
- Pre-trim compatibility shims and removed-product concepts that no longer map
  to the proxy service.

### Known Scope

- Live smoke tests remain opt-in and require credentials or local model servers.
- Provider expansion ideas such as Vertex, Cloudflare Workers AI, Codex CLI, and
  OpenCode bridge are backlog items, not part of this release.
