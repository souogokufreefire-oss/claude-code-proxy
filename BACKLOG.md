# Backlog

> Last updated: 2026-08-17

Tracked work items, ideas, and deferred work. Prioritized within each section.
Items move to `CHANGELOG.md` when shipped.

Priority levels: **P0** (blocking/security), **P1** (next release), **P2** (near-term), **P3** (backlog/idea).

---

## Security & Maintenance

- [x] **(DONE 2026-07-07)** Patch 21 dependabot security advisories (starlette, aiohttp, python-multipart, pydantic-settings)
- [x] **(DONE 2026-07-07)** Bump setup-uv GitHub Action to v8.2.0
- [x] **(DONE 2026-07-07)** Close 6 stale dependabot PRs (#12, #16, #17, #18, #19, #20) — superseded by consolidated dependency upgrade commit
- [x] **(DONE 2026-07-08)** Enable dependabot auto-merge (repo setting flipped via API; minor/patch updates auto-merge after CI)
- [x] **(DONE 2026-07-08)** Cap dependabot PR queue size (uv: 5, github-actions: 3) to prevent future pileup
- [x] **(DONE 2026-08-17)** Pin remaining GitHub Actions to commit SHAs — verified: `actions/checkout@9c091bb` and `astral-sh/setup-uv@f98e069` pinned in `.github/workflows/tests.yml`

## Provider Improvements

- [x] **(DONE 2026-07-07)** Add Kimi provider to CHANGELOG (Unreleased section)
- [x] **(DONE 2026-08-17)** Verify thinking/reasoning support on all 14 providers via smoke tests (commit ef1cf5e; audit-approved)
- [ ] **P2** Smoke-test Cerebras `reasoning_effort` and `clear_thinking` extra_body
- [ ] **P2** Verify vLLM thinking token support (upstream vllm#29915 may be resolved)
- [ ] **P2** Smoke-test Fireworks AI reasoning block filtering (may need ThinkTagParser)

## Provider Expansion (Candidates)

Sourced from `UPSTREAM_AUDIT_PLAN.md` backlog section and community demand:

- [ ] **P3** MiniMax — OpenAI-compatible, popular for agent workflows
- [ ] **P3** Z.AI GLM direct — currently via NIM, native endpoint possible
- [ ] **P3** SambaNova — fast inference, OpenAI-compatible
- [ ] **P3** Vertex AI — Google Cloud Anthropic-compatible endpoint
- [ ] **P3** Codex CLI bridge — OpenAI coding agent routing
- [ ] **P3** OpenCode bridge — alternative coding agent routing
- [ ] **P3** Cloudflare Workers AI — edge inference
- [ ] **P3** DS2API — upstream PR #355, new provider

## Upstream Mining

Tracked in `UPSTREAM_AUDIT_PLAN.md`. Candidates needing local design review:

- [x] **(DONE 2026-08-17)** PR #1002: OpenAI chat reasoning and tool history replay (commit 0723120)
- [ ] **P2** PR #937: DeepSeek cache usage accounting (issue #904: 10x cost when disk-cache tokens dropped)
- [ ] **P2** PR #977: stream:false malformed response fix (file layout mismatch, needs targeted repro)
- [ ] **P2** PR #318: multi-feature (MAX_MESSAGES, CONTEXT_MAX_TOKENS, NIM_PARALLEL_TOOL_CALLS, SSE fix, Claude 4 IDs, tool schema hint) — too broad, needs splitting
- [ ] **P3** PR #341: API key pooling — already in design review, see UPSTREAM_AUDIT_PLAN.md
- [ ] **P3** PR #399: model-cache persistence (closed, may be superseded by #318)

## Observability

- [ ] **P2** Structured request logging with request IDs (adapt from upstream PR #202)
- [ ] **P2** Per-provider latency and error metrics
- [ ] **P2** Startup model-routing log — show effective provider/model per tier
- [ ] **P3** Health endpoint (adapt from upstream PR #270, needs local scope review)

## Context Management

- [x] **(DONE 2026-08-17)** Context Window Manager — Groq payload trimming (`CONTEXT_*` settings, `core/context/context_manager.py`, service-layer integration; audit-approved)
- [ ] **P2** Context usage visibility — surface token counts in response metadata
- [ ] **P2** Graceful context overflow handling (degrade instead of 400)
- [ ] **P3** Optional compaction for long Claude Code sessions
- [ ] **P3** MAX_MESSAGES / CONTEXT_MAX_TOKENS tuning (from upstream PR #318)

## Code Quality

- [ ] **P2** Address starlette 1.x testclient deprecation warning (httpx2 migration)
- [x] **(DONE 2026-07-07)** Clean up `dist/` directory (stale 2.0.0 builds alongside 2.1.0) — local cruft removal, not tracked
- [x] **(DONE 2026-07-07)** Remove `server.log` from repo root — local cruft removal, gitignored

## Documentation

- [x] **(DONE 2026-07-08)** Audit and refresh markdown foundation (HANDOFF, ROADMAP, BACKLOG)
- [ ] **P2** Add CONTRIBUTING.md for community PRs
- [ ] **P3** Architecture decision records (ADRs) for major design choices

## Distribution

- [ ] **P3** PyPI publication (`uv publish`)
- [ ] **P3** Docker image
- [ ] **P3** Homebrew formula

---

## Completed

- [x] 2026-08-17: P2 OpenAI chat reasoning and tool history replay — upstream PR #1002 port (commit 0723120)
- [x] 2026-08-17: P1 Thinking/Reasoning smoke tests — 14-provider smoke matrix, thinking emission and reasoning_content round-trip scenarios (commit ef1cf5e)
- [x] 2026-08-17: Context Window Manager — Groq payload trimming (commits 7f16da1, 50853ad); external Groq TPM 12k limitation registered, not blocking
- [x] 2026-07-08: Upstream audit (since 2026-05-09) — applied PRs #997, #991
- [x] 2026-07-08: Markdown foundation audit and refresh
- [x] 2026-07-08: Enabled dependabot auto-merge (repo setting + config documentation)
- [x] 2026-07-07: Patched 21 security advisories, consolidated 6 dependabot PRs
- [x] 2026-07-07: Created HANDOFF.md, ROADMAP.md, BACKLOG.md
- [x] 2026-07-07: Added Kimi provider to CHANGELOG (Unreleased section)
- [x] 2026-07-07: Removed local cruft (dist/, server.log)
- [x] 2026-05-09: Weekly upstream audit — applied PRs #388, #382, #383, timeout raise
- [x] 2026-04-30: v2.1.0 release — added 7 providers (FriendliAI, Fireworks, vLLM, CLIProxyAPI, Groq, Cerebras, Together)
- [x] 2026-04-29: v2.0.0 release — proxy-only scope, descriptor-driven providers, constant-time auth, OpenAI image conversion
