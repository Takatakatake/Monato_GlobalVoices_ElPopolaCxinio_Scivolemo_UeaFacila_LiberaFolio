"""
Utility helpers to decode Nuxt3 `_payload.json` responses into ordinary Python objects.

Nuxt serialises page data as a flat list. Entries reference each other by integer index,
and certain entries wrap the referenced value in a special structure such as
`["ShallowReactive", <index>]`.  This module performs the recursive lookups and
returns plain dict / list / primitive values that are easier to consume downstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence


class NuxtPayloadDecodeError(RuntimeError):
    """Raised when the payload cannot be decoded."""


@dataclass
class NuxtPayloadDecoder:
    payload: Sequence[Any]
    unwrap_types: Sequence[str] = ("ShallowReactive",)
    _cache: Dict[int, Any] = field(default_factory=dict, init=False)

    def decode(self, index: int = 0) -> Any:
        """Return the decoded object for the given payload index (defaults to root)."""
        if not isinstance(index, int):
            raise NuxtPayloadDecodeError(f"decode index must be int, got {type(index)}")
        return self._resolve(index)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(self, index: int) -> Any:
        if index in self._cache:
            return self._cache[index]
        try:
            raw = self.payload[index]
        except IndexError as exc:  # pragma: no cover - defensive
            raise NuxtPayloadDecodeError(f"payload index out of range: {index}") from exc

        value: Any
        if isinstance(raw, list):
            value = self._resolve_list(raw)
        elif isinstance(raw, dict):
            value = {key: self._decode_value(val) for key, val in raw.items()}
        else:
            value = raw
        self._cache[index] = value
        return value

    def _resolve_list(self, raw: List[Any]) -> Any:
        if not raw:
            return []
        first = raw[0]
        if isinstance(first, str) and first in self.unwrap_types:
            # Special Nuxt wrapper, unwrap the payload stored in the second item.
            if len(raw) < 2:
                raise NuxtPayloadDecodeError(f"Malformed wrapped entry: {raw!r}")
            return self._decode_value(raw[1])
        return [self._decode_value(item) for item in raw]

    def _decode_value(self, value: Any) -> Any:
        if isinstance(value, int) and 0 <= value < len(self.payload):
            return self._resolve(value)
        if isinstance(value, list):
            return [self._decode_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._decode_value(val) for key, val in value.items()}
        return value


def decode_payload(payload: Sequence[Any], *, root_index: int = 0) -> Any:
    """Convenience wrapper returning the decoded object for a payload list."""
    decoder = NuxtPayloadDecoder(payload)
    return decoder.decode(root_index)

