"""Composition-root instance.

Holds the single ``AppContext`` (the assembled pluggable layers) and the
``MemoryService`` for this process. Kept separate from ``context`` (the factory)
and ``server`` (the transport) so the tool wrappers in ``tooling`` can reach the
running context without importing ``server`` (which would be a cycle).
"""

from __future__ import annotations

from .context import build_context
from .service import MemoryService

ctx = build_context()
service = MemoryService(ctx)
