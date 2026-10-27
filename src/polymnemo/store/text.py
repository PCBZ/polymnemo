"""Keyword matching rules shared by every store, so they agree on what a hit is.

A keyword hit is an exact, case-insensitive SUBSTRING match, with every
whitespace-separated term required. Substring rather than tokens because the
point of keyword mode is an ID or an error string, where `order_id=88312`
should match `88312` and stemming would only get in the way. A trigram index
may make it faster, but never changes which rows match.
"""

from __future__ import annotations

# A query with hundreds of words would become hundreds of ILIKE conditions.
# Truncating loosens the match (fewer terms must hold) rather than failing it,
# which is the safer side to err on for a search box.
MAX_TERMS = 8


def keyword_terms(query: str) -> list[str]:
    """The terms a row must contain: unique, in order, capped at MAX_TERMS."""
    seen: list[str] = []
    for term in query.split():
        if term not in seen:
            seen.append(term)
    return seen[:MAX_TERMS]


def like_escape(term: str) -> str:
    """Escape LIKE metacharacters so a term is matched literally.

    Without this a query for `100%` or `a_b` is a wildcard pattern, and an ID
    containing an underscore matches rows it should not.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
