"""polymnemo — a shared long-term memory across any LLM, over MCP.

Principles (see the project wiki):
- Plain text is the single source of truth.
- Zero external / generative-LLM calls (embeddings run locally, deterministically).
- HTTP-native transport (Streamable HTTP at ``/mcp``).
- Three pluggable layers: Auth / Store / Retriever.
- Bounded results with ``limit`` / ``cursor`` pagination; the client decides.
"""

__version__ = "1.0.0"
