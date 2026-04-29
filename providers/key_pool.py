"""Shared API key fallback state for provider transports."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(slots=True)
class _KeyState:
    key: str
    usage_count: int = 0
    failed: bool = False


class ApiKeyPool:
    """Track fallback API keys and rotate away from failed or exhausted keys."""

    def __init__(self, keys: tuple[str, ...], *, usage_limit: int = 0):
        unique_keys: list[str] = []
        for key in keys:
            stripped = key.strip()
            if stripped and stripped not in unique_keys:
                unique_keys.append(stripped)
        self._states = tuple(_KeyState(key) for key in unique_keys)
        self._usage_limit = usage_limit
        self._current_index = 0
        self._lock = RLock()

    @property
    def active_key(self) -> str | None:
        with self._lock:
            state = self._active_state()
            return None if state is None else state.key

    def has_fallbacks(self) -> bool:
        return len(self._states) > 1

    def mark_used(self, key: str) -> None:
        if self._usage_limit <= 0:
            return
        with self._lock:
            state = self._state_for_key(key)
            if state is None:
                return
            state.usage_count += 1

    def mark_failed(self, key: str) -> None:
        with self._lock:
            state = self._state_for_key(key)
            if state is not None:
                state.failed = True

    def rotate_after_failure(self, key: str) -> str | None:
        with self._lock:
            self.mark_failed(key)
            return self._advance_to_next_available()

    def rotate_if_exhausted(self, key: str) -> str | None:
        if self._usage_limit <= 0:
            return self.active_key
        with self._lock:
            state = self._state_for_key(key)
            if state is None or state.usage_count < self._usage_limit:
                return self.active_key
            state.failed = True
            return self._advance_to_next_available()

    def _state_for_key(self, key: str) -> _KeyState | None:
        for state in self._states:
            if state.key == key:
                return state
        return None

    def _active_state(self) -> _KeyState | None:
        if not self._states:
            return None
        state = self._states[self._current_index]
        if self._is_available(state):
            return state
        key = self._advance_to_next_available()
        return None if key is None else self._states[self._current_index]

    def _advance_to_next_available(self) -> str | None:
        if not self._states:
            return None
        for offset in range(1, len(self._states) + 1):
            candidate_index = (self._current_index + offset) % len(self._states)
            candidate = self._states[candidate_index]
            if self._is_available(candidate):
                self._current_index = candidate_index
                return candidate.key
        return None

    def _is_available(self, state: _KeyState) -> bool:
        if state.failed:
            return False
        return self._usage_limit <= 0 or state.usage_count < self._usage_limit
