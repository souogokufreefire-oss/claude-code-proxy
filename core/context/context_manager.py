"""Context Window Manager - prevents payloads from exceeding provider limits."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from core.anthropic.tokens import get_token_count

#: Maximum context tokens budget (excluding reserved output tokens)
CONTEXT_MAX_TOKENS_DEFAULT = 24_000
#: Tokens reserved for the model's output
CONTEXT_RESERVED_OUTPUT_TOKENS_DEFAULT = 4_096
#: Minimum number of most-recent messages to always keep
CONTEXT_MIN_RECENT_MESSAGES_DEFAULT = 10


class ContextBudgetSettings(Protocol):
    """Minimal settings surface consumed by the context manager.

    Kept as a structural protocol so this neutral ``core`` module does not
    depend on the product ``config`` package.
    """

    context_max_tokens: int
    context_reserved_output_tokens: int
    context_min_recent_messages: int


class ContextRequest(Protocol):
    """Structural subset of ``MessagesRequest`` needed for trimming."""

    messages: list[Any]
    system: Any
    tools: list[Any] | None


class ContextResult:
    """Result from :meth:`ContextManager.optimize`."""

    def __init__(
        self,
        request: Any,
        removed_messages: int,
        removed_tokens: int,
        trimmed: bool,
        *,
        budget_tokens: int = 0,
        overflow: bool = False,
    ) -> None:
        self.request: Any = request
        self.removed_messages = removed_messages
        self.removed_tokens = removed_tokens
        self.trimmed = trimmed
        self.budget_tokens = budget_tokens
        # True when the protected core (system + first user + recent + tool
        # cycles) alone exceeds the budget, so trimming cannot fit the payload.
        self.overflow = overflow


class ContextManager:
    """Trim request messages to fit a token budget.

    The system prompt, the first user message, the most recent
    ``context_min_recent_messages`` messages and complete tool_use /
    tool_result cycles are preserved.  The original request is never
    mutated; ``optimize`` always returns a safe copy.
    """

    def __init__(self, settings: ContextBudgetSettings | None = None) -> None:
        self._settings = settings
        self._max_tokens = (
            getattr(settings, "context_max_tokens", CONTEXT_MAX_TOKENS_DEFAULT)
            or CONTEXT_MAX_TOKENS_DEFAULT
        )
        self._reserved_output = (
            getattr(
                settings,
                "context_reserved_output_tokens",
                CONTEXT_RESERVED_OUTPUT_TOKENS_DEFAULT,
            )
            or CONTEXT_RESERVED_OUTPUT_TOKENS_DEFAULT
        )
        self._min_recent = (
            getattr(
                settings,
                "context_min_recent_messages",
                CONTEXT_MIN_RECENT_MESSAGES_DEFAULT,
            )
            or CONTEXT_MIN_RECENT_MESSAGES_DEFAULT
        )
        self._budget = self._max_tokens - self._reserved_output

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, request: ContextRequest) -> ContextResult:
        """Return a trimmed copy of *request* if it exceeds the budget.

        The original *request* is never mutated.
        """
        tokens = self._count_tokens(request)
        if tokens <= self._budget:
            return ContextResult(
                request=request,
                removed_messages=0,
                removed_tokens=0,
                trimmed=False,
                budget_tokens=self._budget,
            )

        trimmed_request = deepcopy(request)
        removed_messages = self._trim_inplace(trimmed_request)
        new_tokens = self._count_tokens(trimmed_request)

        return ContextResult(
            request=trimmed_request,
            removed_messages=removed_messages,
            removed_tokens=tokens - new_tokens,
            trimmed=True,
            budget_tokens=self._budget,
            overflow=new_tokens > self._budget,
        )

    # ------------------------------------------------------------------
    # Token counting
    # ------------------------------------------------------------------

    def _count_tokens(self, request: ContextRequest) -> int:
        return get_token_count(
            messages=request.messages,
            system=request.system,
            tools=request.tools,
        )

    # ------------------------------------------------------------------
    # Trimming logic
    # ------------------------------------------------------------------

    def _trim_inplace(self, request: ContextRequest) -> int:
        """Trim *request.messages* in place; return the number removed."""
        messages = list(request.messages)
        protected = self._protected_indices(messages)
        removed: set[int] = set()

        # Drop messages from the oldest, whole tool cycles at a time,
        # until the remaining payload fits the budget.
        for i in range(len(messages)):
            if i in protected or i in removed:
                continue
            cycle = self._removal_closure(messages, i, protected, removed)
            removed.update(cycle)
            kept = [m for j, m in enumerate(messages) if j not in removed]
            if get_token_count(kept, request.system, request.tools) <= self._budget:
                break

        if not removed:
            return 0

        request.messages = [m for j, m in enumerate(messages) if j not in removed]
        return len(removed)

    def _protected_indices(self, messages: list[Any]) -> set[int]:
        """Return indices that must never be removed."""
        protected: set[int] = set()

        # 1. First user message (conversation root).
        for i, m in enumerate(messages):
            if getattr(m, "role", None) == "user":
                protected.add(i)
                break

        # 2. Most recent messages.
        recent_start = max(len(messages) - self._min_recent, 0)
        protected.update(range(recent_start, len(messages)))

        # 3. Complete tool cycles: when one side of a pair is protected,
        #    the other side must be protected too.
        tool_use_msg, tool_result_msg = self._tool_pair_map(messages)
        for tool_id, use_idx in tool_use_msg.items():
            result_idx = tool_result_msg.get(tool_id)
            if use_idx in protected or (
                result_idx is not None and result_idx in protected
            ):
                protected.add(use_idx)
                if result_idx is not None:
                    protected.add(result_idx)

        return protected

    def _removal_closure(
        self,
        messages: list[Any],
        start: int,
        protected: set[int],
        removed: set[int],
    ) -> set[int]:
        """Return the indices that must be dropped together with *start*.

        Removing a tool_use message requires removing the matching
        tool_result message and vice versa, so the closure keeps walking
        through paired messages until no more are found.
        """
        tool_use_msg, tool_result_msg = self._tool_pair_map(messages)
        closure: set[int] = set()
        stack = [start]

        while stack:
            idx = stack.pop()
            if idx in closure or idx in protected or idx in removed:
                continue
            closure.add(idx)
            for block in self._content_blocks(messages[idx]):
                pair: int | None = None
                block_type = getattr(block, "type", None)
                if block_type == "tool_use":
                    pair = tool_result_msg.get(getattr(block, "id", ""))
                elif block_type == "tool_result":
                    pair = tool_use_msg.get(getattr(block, "tool_use_id", ""))
                if pair is not None and pair not in protected:
                    stack.append(pair)

        return closure

    @staticmethod
    def _content_blocks(message: Any) -> list[Any]:
        """Return the content blocks of a message (string content wrapped)."""
        content = getattr(message, "content", None)
        if isinstance(content, list):
            return content
        return [content]

    @staticmethod
    def _tool_pair_map(
        messages: list[Any],
    ) -> tuple[dict[str, int], dict[str, int]]:
        """Map tool_use ids to message indices for both sides of each pair."""
        tool_use_msg: dict[str, int] = {}
        tool_result_msg: dict[str, int] = {}
        for i, m in enumerate(messages):
            for block in ContextManager._content_blocks(m):
                block_type = getattr(block, "type", None)
                if block_type == "tool_use":
                    tool_use_msg[getattr(block, "id", "")] = i
                elif block_type == "tool_result":
                    tool_result_msg[getattr(block, "tool_use_id", "")] = i
        return tool_use_msg, tool_result_msg
