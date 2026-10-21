# Vendored from PCBZ/rsp examples/gitleaks-py at v0.1.1 (Apache-2.0).
# Unmodified apart from this header. A plugin is a self-contained command,
# so each one carries its own copy -- which is how the upstream examples do
# it. See plugins/gitleaks/README.md for the provenance.
"""One message, refusing what a lenient parser would take (T4).

Not a parser: `json` is the parser. These are the six leniencies T4 names,
which every implementation has somewhere and no two have in the same place.
"""

from __future__ import annotations

import json
from typing import Any

SAFE_INTEGER = 2**53 - 1
WHITESPACE = " \t\n\r"


def loads(raw: str) -> Any:
    """The parsed message, or ValueError naming what the grammar refuses."""
    if raw.strip(WHITESPACE) != raw.strip():
        raise ValueError("framed by something other than space, tab, CR or LF")
    return _within_range(
        json.loads(raw, object_pairs_hook=_no_repeats, parse_constant=_not_json)
    )


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"repeated key {key!r}")
        seen[key] = value
    return seen


def _not_json(token: str) -> Any:
    raise ValueError(f"{token} is not a number")


def _within_range(value: Any) -> Any:
    """Integers JavaScript would round, and strings UTF-8 cannot carry."""
    if isinstance(value, str):
        value.encode("utf-8")  # a lone surrogate raises here
    elif isinstance(value, bool):
        pass
    elif isinstance(value, int) and abs(value) > SAFE_INTEGER:
        raise ValueError(f"{value} is outside ±(2^53 - 1)")
    elif isinstance(value, dict):
        for key, item in value.items():
            _within_range(key)
            _within_range(item)
    elif isinstance(value, list):
        for item in value:
            _within_range(item)
    return value
