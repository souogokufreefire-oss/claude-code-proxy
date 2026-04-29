# Proxy-Only Trim Plan

## Goal

Reduce this repository to one product: a Claude Code compatible Anthropic Messages
proxy with provider routing, streaming normalization, tool-call handling, and
request-scoped model selection.

The current working baseline is important. Before each phase, the proxy should
still start and the current unit test subset for retained behavior should pass.
Do not combine broad deletion with behavior changes.

## Non-Goals

Remove these product surfaces entirely:

- Discord bot
- Telegram bot
- voice note transcription
- remote Claude Code session orchestration
- messaging trees, platform rendering, queue handling, and bot command handling
- live smoke harnesses for messaging, voice, bot clients, and package workflows

Do not remove these proxy capabilities:

- `/v1/messages`
- `/v1/messages/count_tokens`
- `/v1/models`
- `/health`
- provider routing via `MODEL`, `MODEL_OPUS`, `MODEL_SONNET`, `MODEL_HAIKU`
- request model override via auth-token suffix, e.g. `freecc:open_router/...`
- NVIDIA NIM, OpenRouter, DeepSeek, LM Studio, llama.cpp, and Ollama providers
- streaming SSE conversion and native SSE pass-through
- tool use conversion and Anthropic-compatible request models
- provider rate limiting, timeout handling, and safe error messages
- optional local web server tools only if deliberately kept

## Current Core Runtime

Keep these as the proxy spine:

- `server.py`
- `api/app.py`
- `api/routes.py`
- `api/services.py`
- `api/model_router.py`
- `api/dependencies.py`
- `api/models/`
- `api/optimization_handlers.py`
- `api/detection.py`
- `api/validation_log.py`
- `config/`
- `core/`
- `providers/`
- `tests/api/`
- `tests/config/`
- `tests/core/`
- `tests/providers/`
- proxy-relevant `tests/contracts/`

Review before keeping:

- `api/web_tools/`
- `api/web_server_tools.py`
- `api/command_utils.py`
- `claude-pick`
- `nvidia_nim_models.json`

Remove or replace:

- `messaging/`
- `cli/manager.py`
- `cli/session.py`
- `cli/process_registry.py`
- `tests/messaging/`
- bot/voice/CLI smoke tests
- package dependencies that exist only for messaging or voice

## Phase 0: Freeze Baseline

Purpose: make the current known-good state recoverable.

Tasks:

1. Create a new git baseline commit before trimming.
2. Confirm `.env` is not tracked and no provider keys are committed.
3. Run the existing checks once:

```bash
uv run ruff format
uv run ruff check
uv run ty check
uv run pytest
```

Acceptance:

- Current tests pass.
- Manual Claude Code launch through the proxy works.
- A remote branch exists for the baseline.

## Phase 1: Make Runtime Proxy-Only

Purpose: remove messaging startup from the web server without deleting modules yet.

Tasks:

1. Simplify `api/runtime.py` so `AppRuntime` owns only:
   - `ProviderRegistry`
   - auth warning
   - provider cleanup on shutdown
2. Remove `_start_messaging_if_configured`, `_start_message_handler`,
   `_restore_tree_state`, and messaging limiter shutdown.
3. Simplify `/stop` in `api/routes.py`.
   - Preferred: remove the endpoint entirely if Claude Code does not need it.
   - Alternative: keep it as a compatibility no-op returning `410` or `204`.
4. Remove `TYPE_CHECKING` imports of messaging and CLI types.
5. Remove `cli.process_registry.kill_all_best_effort()` from `server.py` and
   `cli/entrypoints.py`.

Tests to run:

```bash
uv run pytest tests/api tests/providers tests/config tests/core tests/contracts
uv run ruff check
uv run ty check
```

Acceptance:

- Server starts without importing `messaging`.
- Provider registry is still app-scoped.
- `/v1/messages`, `/v1/models`, `/health`, and token counting still work.

## Phase 2: Trim Settings And Env Surface

Purpose: remove user-facing configuration for removed features.

Remove from `config/settings.py`:

- `messaging_platform`
- `messaging_rate_limit`
- `messaging_rate_window`
- `voice_note_enabled`
- `whisper_device`
- `whisper_model`
- `hf_token`
- `telegram_bot_token`
- `allowed_telegram_user_id`
- `discord_bot_token`
- `allowed_discord_channels`
- `claude_workspace`
- `allowed_dir`
- `claude_cli_bin`
- `max_message_log_entries_per_chat`
- `log_raw_messaging_content`
- `log_raw_cli_diagnostics`
- `log_messaging_error_details`
- `debug_platform_edits`
- `debug_subagent_stack`

Remove from `.env.example` and README:

- messaging platform config
- voice transcription config
- bot tokens
- Claude workspace/session settings
- messaging-specific diagnostic flags

Keep:

- provider API keys
- provider base URLs
- model routing
- thinking toggles
- provider proxies
- provider rate limit/concurrency
- HTTP timeout settings
- `ANTHROPIC_AUTH_TOKEN`
- raw API/SSE/error logging
- optional web server tools settings, if retained

Tests to update:

- `tests/config/test_config.py`
- `tests/api/test_app_lifespan_and_errors.py`
- any contract tests that assert feature manifests include messaging/voice

Acceptance:

- A minimal proxy-only `.env.example` is understandable without bot sections.
- Settings instantiate with no messaging/voice concepts.
- No retained test imports removed settings.

## Phase 3: Delete Messaging And Voice Modules

Purpose: physically remove unused product code.

Delete:

- `messaging/`
- `tests/messaging/`
- `providers/nvidia_nim/voice.py`
- voice-only tests under `smoke/`
- voice optional dependencies from `pyproject.toml`
- voice unresolved import allowances from `pyproject.toml`

Remove dependencies from `pyproject.toml`:

- `python-telegram-bot`
- `discord.py`
- voice extras: `grpcio`, `grpcio-tools`, `nvidia-riva-client`
- voice local extras: `torch`, `transformers`, `accelerate`, `librosa`

Review whether `aiohttp` is still needed after messaging removal. Keep only if
proxy/web tooling still imports it.

Acceptance:

```bash
rg "messaging|telegram|discord|voice_note|WHISPER|whisper|riva|librosa|torch|transformers" \
  api config core providers tests pyproject.toml README.md .env.example
```

The command should return only intentional historical notes, or nothing.

## Phase 4: Remove CLI Session Orchestration

Purpose: keep package entry points but remove bot-owned Claude Code process
management.

Delete:

- `cli/manager.py`
- `cli/session.py`
- `cli/process_registry.py`
- `tests/cli/test_cli.py`
- `tests/cli/test_cli_manager_edge_cases.py`
- `tests/cli/test_cli_ownership.py`
- `tests/cli/test_process_registry.py`

Keep or simplify:

- `cli/entrypoints.py`
  - `serve`: starts the FastAPI proxy
  - `init`: writes `.env.example`
- `tests/cli/test_entrypoints.py`, rewritten for the reduced entry points

Update `pyproject.toml`:

- Keep `free-claude-code = "cli.entrypoints:serve"` if package install remains useful.
- Keep `fcc-init = "cli.entrypoints:init"` if config scaffolding remains useful.
- Remove `messaging` from wheel packages.

Acceptance:

- Installed command still starts the proxy.
- No retained code starts a Claude Code subprocess.

## Phase 5: Decide Web Server Tools

Purpose: choose whether this fork is strictly a provider proxy or also a local
web-search/web-fetch executor.

Option A: keep web tools.

- Keep `api/web_tools/`
- Keep `ENABLE_WEB_SERVER_TOOLS`
- Keep related tests.
- Document SSRF risks clearly.

Option B: remove web tools.

- Delete `api/web_tools/`
- Delete `api/web_server_tools.py` if unused.
- Remove `ENABLE_WEB_SERVER_TOOLS`, `WEB_FETCH_ALLOWED_SCHEMES`,
  `WEB_FETCH_ALLOW_PRIVATE_NETWORKS`.
- Remove web-tool tests.
- Keep provider-side tool call conversion.

Recommendation: keep them disabled by default for the first trim, then decide
after the rest of the cleanup is stable.

## Phase 6: Smoke Harness Reduction

Purpose: keep useful live checks without carrying the old product matrix.

Delete:

- `smoke/product/test_voice_product_live.py`
- `smoke/product/test_messaging_product_live.py`
- `smoke/product/test_live_platform_product_live.py`
- `smoke/prereq/test_voice_prereq_live.py`
- `smoke/prereq/test_messaging_prereq_live.py`
- CLI package smoke tests that launch Claude subprocesses unless still needed

Keep or rewrite:

- provider live smoke tests
- API/auth smoke tests
- local provider endpoint smoke tests
- client shape tests that validate Claude Code compatibility

Update:

- `smoke/features.py`
- `smoke/capabilities.py`
- `smoke/README.md`
- contract tests for smoke tiers/capabilities

Acceptance:

- Smoke docs describe proxy/provider tests only.
- No smoke target requires Telegram, Discord, voice, or bot state.

## Phase 7: Documentation And Naming

Purpose: make the fork’s identity and scope explicit.

Update:

- `README.md`
  - rename to `claude-code-proxy`
  - quick start for proxy-only usage
  - model override launcher workflow
  - supported provider table
  - minimal `.env`
  - troubleshooting for 401 probes and provider 429/overload
- `pyproject.toml`
  - package name and description
  - wheel package list
- `LICENSE`
  - preserve original license terms and attribution
- `AGENTS.md` / `CLAUDE.md`
  - remove messaging/voice directives
  - keep proxy architecture rules

Acceptance:

- README no longer advertises features that do not exist.
- Package metadata matches the fork.

## Phase 8: Final Verification Matrix

Run deterministic checks:

```bash
uv run ruff format
uv run ruff check
uv run ty check
uv run pytest
```

Run manual proxy checks:

```bash
curl -sS http://localhost:8082/health
curl -sS -H 'x-api-key: freecc' http://localhost:8082/
curl -sS -H 'x-api-key: freecc:open_router/google/gemma-4-26b-a4b-it:free' \
  http://localhost:8082/v1/models
```

Run Claude Code smoke:

```bash
free-claude --model open_router/google/gemma-4-26b-a4b-it:free
```

Prompt:

```text
Summarize this repository in 10 bullets. Do not edit files.
```

Acceptance:

- Proxy starts.
- Auth-token model suffix still routes correctly.
- Claude Code can complete a read-only task.
- Provider 429/overload errors are user-visible and do not crash the proxy.

## Risk Register

- Removing `cli/process_registry.py` without first removing messaging-owned
  subprocess startup can leave stale imports in `server.py` and `cli/entrypoints.py`.
- Removing settings before runtime is simplified will break `AppRuntime`.
- Deleting smoke capability metadata without updating contract tests will produce
  noisy failures unrelated to proxy behavior.
- Removing web tools changes behavior for Claude Code requests that use server
  `web_search` or `web_fetch`; decide deliberately.
- Full test count will drop substantially. That is expected, but retained tests
  should cover all proxy behavior.

## Suggested First PR

Make the first PR small:

1. Simplify `api/runtime.py` to proxy-only lifecycle.
2. Simplify or remove `/stop`.
3. Remove `cli.process_registry` use from entry points.
4. Update only the tests directly affected by those imports.
5. Run full checks.

Do not delete `messaging/` in the first PR. Once the server no longer imports it,
the deletion becomes mechanical and much safer.
