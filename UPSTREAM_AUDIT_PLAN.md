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

## Fresh Session Prompt

Use this when starting a future maintenance session:

```text
Review current pull requests and issues in Alishahryar1/free-claude-code against
this repository. Use UPSTREAM_AUDIT_PLAN.md as the maintenance workflow. Classify
each relevant item as apply/adapt/backlog/skip, then implement only the safest
focused batch with tests. Keep this fork's provider registry descriptor-driven,
preserve existing retry semantics, and run the repo checks before summarizing.
```

Before implementation, refresh the upstream list instead of trusting the last
recorded candidates. Issues and PRs can change state, receive better repros, or
be superseded by newer work.

## Upstream Attribution And Notifications

- Keep upstream PR/issue numbers in commit messages and changelog-style notes.
- Preserve direct attribution in summaries when a local change is based on a
  specific upstream PR or issue.
- Do not spam upstream authors on every adapted implementation.
- It is reasonable to comment upstream when the local implementation materially
  helps the original reporter or author, especially for open issues. Keep the
  comment factual: link the commit/PR in this fork, state whether it was copied
  or adapted, and mention any behavior differences.
- Avoid implying ownership of the upstream project or asking users to migrate.
  If a user asks where a fix exists, point them to the relevant commit or release
  in this fork.

## CI Expectations

GitHub Actions should continue to enforce:

- no `# type: ignore` / `# ty: ignore` suppressions
- `uv run ruff format --check`
- `uv run ruff check`
- `uv run ty check`
- `uv run pytest`

If the workflow changes, update this section and `AGENTS.md` / `CLAUDE.md`
together.

## Current Candidates

### Pre-Release Audit - 2026-04-29

- [x] Refreshed upstream PRs and issues before the `2.0.0` release.
- [x] No remaining upstream item is a release blocker after applying/adapting
  PRs #259, #262, #264, #271 and the issue #265 class of tool-message repair.
- [x] PR #270: backlog/adapt. The health endpoint idea is useful, but the patch
  is broad and includes AgentRouter docs outside this fork's local proxy scope.
- [x] PR #202: adapt only after release. It mixes reliability fixes, behavior
  changes, logging changes, request IDs, and health metadata; any useful pieces
  need separate local review and tests.
- [x] Issue #223: no pre-release action. It describes DeepSeek reasoning replay
  through the upstream OpenAI-style converter; this fork's DeepSeek provider
  uses the native Anthropic-compatible endpoint and strips OpenAI-helper
  `reasoning_content`.
- [x] Issue #248: documentation/support class. The report was caused by setting
  `NVIDIA_NIM_API_KEY` in `~/.env`; this fork documents `.env` setup and
  packaged `ccp-init`.
- [x] Current timeout/provider-failure issues (#272, #258, #254, #244, #232,
  #231) do not include enough proxy-specific reproduction detail to block the
  release. Keep monitoring them after release.

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

- [x] PR #271 / Issue #260: multimodal user image support for OpenAI-compatible
  conversion
  - Local gap: user `image` content blocks from VS Code/Claude Code were rejected
    before NVIDIA NIM dispatch.
  - Expected change: convert Anthropic user image blocks to OpenAI `image_url`
    parts for base64 and URL sources while keeping text-only messages as flat
    strings.
  - Tests: base64 images, URL images, mixed text/images, invalid source type,
    injection path coverage, and assistant image rejection.

## Design Review Required

- [x] PR #205: API key fallback and usage tracking
  - Relevant to provider rate-limit resilience, but too broad to cherry-pick
    directly.
  - Local decision needed: whether key rotation belongs in provider transports,
    provider config, or a shared credential pool.
  - Must not conflict with the existing retry/backoff and user-facing error
    mapping.
  - Design review result: adapt, do not cherry-pick. The upstream patch mixes
    key rotation into transport retry loops, adds mutable defaults to
    `ProviderConfig`, and hardcodes per-provider key settings in
    `providers.registry`.
  - Local target shape:
    - Added shared credential-list metadata to `config.provider_catalog` so
      `providers.registry` stays descriptor-driven.
    - Added immutable fallback-key fields to `ProviderConfig` only if the
      transports consume them in the same change.
    - Kept current `GlobalRateLimiter.execute_with_retry` behavior for transient
      upstream failures; rotate keys only for credential/quota failures that are
      demonstrably key-scoped.
    - Added provider-specific transport tests for 401/429 rotation before
      enabling the feature.

- [x] PR #261: startup model-routing logs
  - Useful observability, low urgency.
  - Local decision needed: exact log format and whether to include per-tier
    effective provider/model routing at startup.

- [x] Issues #263 and #265: long-session context failures
  - Likely needs targeted reproduction with Claude Code transcripts or live
    smoke coverage.
  - Track separately from generic provider retry work.
  - Review result: issue #263 is a closed context-window overflow report, not a
    proxy bug.
  - Local fix for #265 class: OpenAI-chat conversion now repairs invalid tool
    message sequences before provider dispatch. Orphaned `tool_result` blocks
    are preserved as user-visible text, and deferred assistant text after a
    tool call gets an explicit placeholder tool result when the client omitted
    one. This avoids provider 400s that would otherwise persist until `/clear`.

## Backlog

- Provider expansion PRs: Vertex, Cloudflare Workers AI, MiniMax, Codex CLI,
  OpenCode bridge.
- Context usage visibility and compaction support ideas.
- Documentation-only platform fixes that still apply after the README rewrite.

## Skip Unless Product Scope Changes

- Telegram/bot-only PRs and issues.
- Legacy syntax cleanup already covered by the Python 3.14 toolchain.
- Pre-trim CLI/session-management changes that no longer map to this proxy.
