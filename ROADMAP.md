# Roadmap

> Last updated: 2026-08-17

Directional guide for `claude-code-proxy`. Items here are intentions, not
commitments. For tracked work items, see `BACKLOG.md`.

## Current State (v2.2.0)

Stable, secure, fully functional proxy with 14 provider backends:

- **Anthropic Messages transport (9):** DeepSeek, OpenRouter, LM Studio,
  llama.cpp, Ollama, FriendliAI, Fireworks AI, vLLM, CLIProxyAPI
- **OpenAI Chat transport (5):** NVIDIA NIM, Groq, Cerebras, Together AI, Kimi

Per-tier model routing (Opus/Sonnet/Haiku/fallback), streaming, tool use,
thinking/reasoning blocks, OpenAI chat reasoning and tool history replay,
Context Window Manager (Groq payload trimming), image input conversion,
fallback key rotation, local request optimizations, and optional web server
tools.

CI enforces formatting, linting, type checking, and 987 tests with zero
type-suppression tolerance.

## Near-Term (Next Release)

### Provider Hardening

- [x] Smoke-test coverage for all 14 providers against live endpoints
      (commit `ef1cf5e`)
- [x] Verify thinking/reasoning support per provider (some marked
      conservatively)
- [x] Expand OpenAI-chat converter edge case coverage (reasoning and tool
      history replay, commit `0723120`)

### Kimi Provider Documentation

- [x] Kimi provider documented in README provider table and CHANGELOG (2.2.0)

### Dependency Hygiene

- Keep dependabot PRs merged promptly (weekly cadence)
- Monitor starlette 1.x migration notes (testclient httpx2 transition)
- Track openai SDK major versions for breaking changes

## Mid-Term

### Observability

- Structured request/response logging with request IDs
- Per-provider latency and error rate metrics
- Startup model-routing log (which providers are configured per tier)

### Provider Expansion (Backlog Candidates)

See `BACKLOG.md` and `UPSTREAM_AUDIT_PLAN.md` for tracked candidates:

- **MiniMax** — popular in the AI agent ecosystem, OpenAI-compatible
- **Z.AI GLM direct** — currently routed through NIM, could add native
- **SambaNova** — fast inference, OpenAI-compatible
- **Vertex AI** — Google Cloud Anthropic-compatible endpoint
- **Codex CLI / OpenCode bridge** — coding-agent-specific routing

All new providers follow the existing descriptor-driven pattern (see
`docs/plans/2026-04-29-new-upstream-providers.md` for the worked example).

### Context Management

- Context usage visibility (token counting, context window awareness)
- Smart context overflow handling (graceful degradation instead of 400)
- Optional compaction for long Claude Code sessions

## Long-Term

### Architecture Evolution

- Evaluate async provider transport refactoring for improved concurrency
- Consider provider health checking and automatic failover
- Plugin architecture for user-contributed providers (if community grows)

### Client Compatibility

- Track Claude Code client protocol changes (Anthropic API version bumps)
- Maintain compatibility with VS Code and JetBrains ACP as they evolve
- Test against new Claude Code features (MCP, agent mode, etc.)

### Distribution

- PyPI publication for `pip install claude-code-proxy`
- Docker image for containerized deployment
- Homebrew formula for macOS install (`brew install claude-code-proxy`)

## Non-Goals

- This is a **proxy**, not a chat application. No UI, no conversation management.
- No Telegram/bot integration (removed in 2.0.0 trim — those belong upstream).
- No model hosting or fine-tuning — this routes to existing providers.
- Not a replacement for Claude Code itself — it's the plumbing between Claude
  Code and your chosen inference backend.

## Release Process

1. Run full CI: `make ci`
2. Run upstream audit: follow `UPSTREAM_AUDIT_PLAN.md`
3. Update `CHANGELOG.md`
4. Bump version in `pyproject.toml`
5. Tag: `git tag v<version>`
6. Push: `git push --tags`
7. Build: `uv build` (outputs to `dist/`)
8. (Future) Publish to PyPI
