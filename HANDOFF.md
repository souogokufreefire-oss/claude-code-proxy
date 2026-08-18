# Handoff Document

> Last updated: 2026-08-17

This document gives a new contributor (human or agent) enough context to
resume work on this repository without reading every file.

## Recent Work (2026-08-17)

- Context Window Manager — Groq payload trimming (`CONTEXT_*` settings,
  `core/context/context_manager.py`, service-layer integration).
- P1 thinking/reasoning smoke coverage for all 14 providers (commit `ef1cf5e`).
- P2 OpenAI chat reasoning and tool history replay, ported from upstream
  PR #1002 (commit `0723120`).

## What This Project Is

`claude-code-proxy` is an Anthropic-compatible proxy that routes Claude Code
CLI, VS Code, and JetBrains ACP traffic to upstream model providers. It keeps
Claude Code's client-side protocol stable while letting the operator choose
where inference actually happens.

- **Version:** 2.2.0
- **Python:** 3.14+ (enforced)
- **Package manager:** uv (astral)
- **Framework:** FastAPI + httpx + openai SDK
- **License:** MIT
- **Upstream origin:** Forked from `Alishahryar1/free-claude-code`, trimmed to
  proxy-only scope. Upstream relationship is tracked in
  `UPSTREAM_AUDIT_PLAN.md`.

## Quick Start (Development)

```bash
git clone https://github.com/suparious/claude-code-proxy.git
cd claude-code-proxy
uv sync --locked --group dev    # install deps
uv run ruff format              # format
uv run ruff check               # lint
uv run ty check                 # type check
uv run pytest                   # tests (992 tests, ~7s)
```

Or use the Makefile: `make format`, `make lint`, `make ty`, `make test`,
`make ci` (runs all four in order).

The CI-enforced check order is: format, lint, type, test. All must pass.

## Architecture Overview

See `PLAN.md` for the authoritative architecture guide. Summary:

```
config/          Environment-backed settings, provider catalog, logging
core/anthropic/  Neutral Anthropic protocol helpers (SSE, tokens, content, tools)
api/             HTTP routes, request orchestration, model routing, auth, server
providers/       Upstream model adapters (14 providers, 2 transport archetypes)
cli/             Installed package entrypoints (claude-code-proxy, ccp-init)
smoke/           Opt-in live product smoke tests (not run in CI by default)
tests/           Deterministic unit + contract tests (992 tests)
```

### Dependency Direction

```
config → core.anthropic → providers → api → cli
```

Shared protocol logic lives in `core/anthropic/`. Provider adapters may depend
on the neutral protocol layer, but API code must not import provider internals.
This is enforced by contract tests in `tests/contracts/test_import_boundaries.py`.

### Provider Architecture

Two transport archetypes, both descriptor-driven via `config/provider_catalog.py`:

1. **AnthropicMessagesTransport** — native Anthropic Messages API (DeepSeek,
   OpenRouter, LM Studio, llama.cpp, Ollama, FriendliAI, Fireworks, vLLM,
   CLIProxyAPI). Minimal: auth header override + optional request body
   customization. ~30 lines per provider.

2. **OpenAIChatTransport** — OpenAI chat completions with Anthropic conversion
   (NVIDIA NIM, Groq, Cerebras, Together, Kimi). Moderate: full request body
   conversion + reasoning handling. ~100-250 lines per provider.

Each provider touches 4 registration points: `config/provider_catalog.py`,
`config/settings.py`, `providers/defaults.py`, `providers/registry.py`.

### Adding A New Provider

See `docs/plans/2026-04-29-new-upstream-providers.md` for a detailed worked
example with code for both transport types. The checklist:

1. Add `ProviderDescriptor` to `config/provider_catalog.py`
2. Add settings fields to `config/settings.py` (API key, keys tuple, limits, proxy)
3. Add default base URL constant to `providers/defaults.py`
4. Create `providers/<name>/__init__.py` + `client.py` (and `request.py` for OpenAI chat type)
5. Register factory function in `providers/registry.py`
6. Write tests in `tests/providers/test_<name>.py`
7. Update `.env.example`, `README.md`, smoke capability metadata

## Key Files Reference

| File | Purpose |
|------|---------|
| `PLAN.md` | Architecture plan, dependency direction, boundary rules |
| `UPSTREAM_AUDIT_PLAN.md` | Upstream mining workflow and candidate tracking |
| `AGENTS.md` / `CLAUDE.md` | Agent coding directive (identical, kept in sync) |
| `pyproject.toml` | Project metadata, dependencies, ruff/pytest/ty config |
| `Makefile` | Shortcuts: format, lint, ty, test, ci, smoke-* targets |
| `.env.example` | Canonical list of all environment variables |
| `config/provider_catalog.py` | Provider descriptors (the source of truth for provider metadata) |
| `config/settings.py` | Pydantic Settings model (all env-backed config) |
| `providers/registry.py` | Provider factory registry (descriptor-driven) |
| `providers/base.py` | BaseProvider, ProviderConfig, transport base classes |
| `api/app.py` | FastAPI ASGI factory (`create_app`) |
| `api/routes.py` | HTTP route definitions |
| `api/model_router.py` | Per-tier model routing logic (Opus/Sonnet/Haiku/fallback) |
| `api/dependencies.py` | Auth, provider resolution, request-scoped dependencies |
| `server.py` | Module-level app instance for `uvicorn server:app` |
| `tests/contracts/` | Architecture contract tests (import boundaries, CI workflow, smoke tiers) |

## CI

`.github/workflows/tests.yml` runs on push/PR to main/master:

1. Reject `# type: ignore` / `# ty: ignore` suppressions
2. `uv run ruff format --check`
3. `uv run ruff check`
4. `uv run ty check`
5. `uv run pytest`

Actions are pinned to commit SHAs (not tags) for supply-chain safety.

Dependabot is configured for weekly uv and github-actions updates
(`.github/dependabot.yml`). Minor/patch updates are grouped and auto-merge
after CI passes (major version bumps like starlette 0.x→1.x still need
manual review). PR queue is capped (uv: 5, github-actions: 3) to prevent
pileup. Auto-merge requires the repo setting `Allow auto-merge` to be
enabled (it is).

## Smoke Tests

Live smoke tests live under `smoke/` and are opt-in (`FCC_LIVE_SMOKE=1`).
They require real provider credentials or local model servers. Not run in CI.

```bash
make smoke-collect              # list available smoke scenarios
make smoke-live                 # run all live smoke (needs FCC_LIVE_SMOKE=1)
make smoke-targets              # run product smoke only
```

Smoke results are written to `.smoke-results/` (gitignored).

## Known Warnings

- Starlette 1.x deprecation: `starlette.testclient` recommends `httpx2` for
  test clients. This is a cosmetic warning in FastAPI's testclient import and
  does not affect functionality. Non-blocking.

## Signing

- Commits are GPG-signed with key `81F5BD471273814D`
  (full fingerprint `70D493F74B02B642FCB438D481F5BD471273814D`).
- Verified email on GitHub: `shaun@solidrust.net` (added 2026-07-08).
- GPG public key is registered on the GitHub account (added 2026-07-08).
  Commits show as "Verified" on GitHub.

## How To Resume Work

1. Read this file and `PLAN.md`.
2. Check `git log --oneline -20` for recent activity.
3. Check open PRs: `gh pr list --state open`.
4. Check security alerts: `gh api repos/suparious/claude-code-proxy/dependabot/alerts --paginate -q '.[] | select(.state=="open") | .dependency.package.name'`.
   (Currently zero open — last sweep on 2026-07-07 closed all 21.)
5. Run `make ci` to confirm the baseline is green (992 tests, ~7s).
6. Check `BACKLOG.md` for prioritized work items.
7. Check `ROADMAP.md` for directional context.
8. For upstream mining, follow `UPSTREAM_AUDIT_PLAN.md`.
