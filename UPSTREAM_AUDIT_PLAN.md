# Upstream Audit Plan

This plan tracks work mined from the original
`Alishahryar1/free-claude-code` repository. Keep using it until this fork has its
own active user/reporting loop, or until the upstream community has moved over.

## Audit Cadence

- Run a quick upstream audit weekly while active development is ongoing.
- Run an audit before each tagged release.
- Run an immediate audit when a user reports provider failures, rate limits,
  malformed responses, context-length failures, or Claude Code client breakage.
- Prefer small, reviewable cherry-picks. Broad upstream features need local
  design review before implementation.

## Audit Workflow

1. Check the local tree is clean.
2. Review recent upstream pull requests:
   `gh pr list --repo Alishahryar1/free-claude-code --state all --limit 30`.
3. Review recent upstream issues:
   `gh issue list --repo Alishahryar1/free-claude-code --state all --limit 50`.
4. Classify candidates as:
   - `apply`: small, relevant, low-risk fixes.
   - `adapt`: useful idea, but needs local architecture changes.
   - `backlog`: feature/provider expansion outside current focus.
   - `skip`: obsolete, bot/Telegram-only, or incompatible with this fork.
5. Apply one candidate at a time with focused tests.
6. Run checks in repo order:
   `uv run ruff format`, `uv run ruff check`, `uv run ty check`,
   `uv run pytest`.
7. Record the upstream PR/issue number in the commit message.

## Current Candidates

### Apply

- [x] PR #262: `fix(security): constant-time comparison for ANTHROPIC_AUTH_TOKEN`
  - Local gap: `api/dependencies.py` still uses direct string comparison for
    `ANTHROPIC_AUTH_TOKEN`.
  - Expected change: use `secrets.compare_digest` after preserving existing
    token suffix behavior.
  - Tests: auth success/failure plus a focused assertion that constant-time
    comparison is used.

- [x] PR #264: `fix: validate smoke config env inputs`
  - Local gap: `smoke/lib/config.py` parses `FCC_SMOKE_TIMEOUT_S` with raw
    `float(...)` and model provider parsing can fail with generic errors.
  - Expected change: add explicit timeout/model parsing helpers with clear
    `ValueError` messages.
  - Tests: invalid timeout, blank smoke model override, mismatched provider
    prefix, and unknown provider prefix.

### Apply After The Security/Smoke Fixes

- [x] PR #259: `feat(nim): auto-prefix vendor namespace for short NIM model names`
  - Local gap: `providers/nvidia_nim/request.py` forwards short NIM model names
    unchanged.
  - Expected change: map common short NIM model families to provider vendor
    namespaces while leaving already-qualified names unchanged.
  - Tests: mapped families, already-qualified models, empty/non-string inputs.

## Design Review Required

- [ ] PR #205: API key fallback and usage tracking
  - Relevant to provider rate-limit resilience, but too broad to cherry-pick
    directly.
  - Local decision needed: whether key rotation belongs in provider transports,
    provider config, or a shared credential pool.
  - Must not conflict with the existing retry/backoff and user-facing error
    mapping.

- [ ] PR #261: startup model-routing logs
  - Useful observability, low urgency.
  - Local decision needed: exact log format and whether to include per-tier
    effective provider/model routing at startup.

- [ ] Issues #263 and #265: long-session context failures
  - Likely needs targeted reproduction with Claude Code transcripts or live
    smoke coverage.
  - Track separately from generic provider retry work.

## Backlog

- Provider expansion PRs: Vertex, Cloudflare Workers AI, MiniMax, Codex CLI,
  OpenCode bridge.
- Context usage visibility and compaction support ideas.
- Documentation-only platform fixes that still apply after the README rewrite.

## Skip Unless Product Scope Changes

- Telegram/bot-only PRs and issues.
- Legacy syntax cleanup already covered by the Python 3.14 toolchain.
- Pre-trim CLI/session-management changes that no longer map to this proxy.
