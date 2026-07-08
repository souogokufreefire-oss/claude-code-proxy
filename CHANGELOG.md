# Changelog

## Unreleased

### Added

- Kimi / Moonshot provider using OpenAI-compatible chat completions at
  `https://api.moonshot.ai/v1` with bearer authentication. Reasoning history is
  replayed as `reasoning_content` for tool-call turns when thinking is enabled.
  Adapted from upstream PR #335.

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
