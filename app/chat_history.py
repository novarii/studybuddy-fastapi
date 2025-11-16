"""In-memory chat history storage for dev usage."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from threading import Lock
from typing import DefaultDict, Dict, List

_DEFAULT_USER = "anonymous"


class InMemoryChatHistory:
    """Simple thread-safe chat history store that lives with the process."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._history: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)

    def _key(self, user_id: str | None) -> str:
        return (user_id or _DEFAULT_USER).strip() or _DEFAULT_USER

    def log_exchange(
        self,
        *,
        user_id: str | None,
        user_message: str,
        agent_reply: str,
        source: str,
    ) -> None:
        timestamp = datetime.utcnow().isoformat()
        payload = [
            {"role": "user", "message": user_message, "timestamp": timestamp, "source": source},
            {"role": "agent", "message": agent_reply, "timestamp": timestamp, "source": source},
        ]
        key = self._key(user_id)
        with self._lock:
            self._history[key].extend(payload)

    def get_history(self, user_id: str | None) -> List[Dict[str, str]]:
        key = self._key(user_id)
        with self._lock:
            return list(self._history.get(key, []))

    def all_histories(self) -> Dict[str, List[Dict[str, str]]]:
        with self._lock:
            return {user_id: list(entries) for user_id, entries in self._history.items()}

    def clear(self, user_id: str | None = None) -> None:
        with self._lock:
            if user_id is None:
                self._history.clear()
            else:
                key = self._key(user_id)
                self._history.pop(key, None)
