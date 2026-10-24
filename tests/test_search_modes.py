"""Search modes (#17): similarity, keyword, and rrf.

The properties worth pinning are the ones a user would be hurt by: keyword mode
must find an exact string and ONLY rows containing it, a 2-character Chinese
word must be found in the middle of a sentence, and `has_more` must not promise
a page that comes back empty.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from polymnemo.context import build_context
from polymnemo.models import Memory, new_id
from polymnemo.retriever import HybridRetriever, rrf_fuse
from polymnemo.service import MemoryService
from polymnemo.store import InMemoryStore
from polymnemo.store.text import MAX_TERMS, keyword_terms, like_escape


def _mem(content, *, user="alice", ns="shared", mid=None, **kw) -> Memory:
    return Memory(id=mid or new_id(), user_id=user, namespace=ns, content=content, **kw)


def _store(*rows: Memory) -> InMemoryStore:
    store = InMemoryStore(shared_namespaces=["shared"])
    for row in rows:
        store.add(row, [0.0])
    return store


class TestTermParsing:
    def test_terms_are_split_on_whitespace_and_deduplicated(self):
        assert keyword_terms("  order  88312 order\t88312 ") == ["order", "88312"]

    def test_the_number_of_terms_is_capped(self):
        many = " ".join(f"t{i}" for i in range(MAX_TERMS + 10))
        assert len(keyword_terms(many)) == MAX_TERMS

    def test_an_empty_query_has_no_terms(self):
        assert keyword_terms("   ") == []

    @pytest.mark.parametrize(
        "raw,escaped", [("100%", "100\\%"), ("a_b", "a\\_b"), ("a\\b", "a\\\\b")]
    )
    def test_like_metacharacters_are_escaped(self, raw, escaped):
        """Unescaped, a search for `a_b` is a wildcard and matches `axb`."""
        assert like_escape(raw) == escaped


class TestInMemoryKeywordSearch:
    def test_an_exact_string_is_found(self):
        store = _store(_mem("deploy failed on order 88312"), _mem("unrelated note"))
        hits = store.search_text("alice", "shared", "88312", 10)
        assert [h.content for h in hits] == ["deploy failed on order 88312"]

    def test_only_rows_containing_the_term_come_back(self):
        """The difference from similarity, which ranks the whole namespace."""
        store = _store(_mem("alpha"), _mem("beta"), _mem("gamma"))
        assert len(store.search_text("alice", "shared", "alpha", 10)) == 1

    def test_matching_ignores_case(self):
        store = _store(_mem("Project ORION kickoff"))
        assert store.search_text("alice", "shared", "orion", 10)

    def test_every_term_is_required(self):
        store = _store(_mem("orion kickoff"), _mem("orion"), _mem("kickoff"))
        hits = store.search_text("alice", "shared", "orion kickoff", 10)
        assert [h.content for h in hits] == ["orion kickoff"]

    def test_a_two_character_chinese_word_is_found_mid_sentence(self):
        """The case a trigram-only design would likely miss: trigrams pad on word
        boundaries and an unspaced sentence is one word, so 咖啡 inside it shares
        no trigram with the query. Substring matching does not care."""
        store = _store(_mem("我喜欢深烘咖啡每天早上"))
        assert store.search_text("alice", "shared", "咖啡", 10)

    def test_a_longer_chinese_term_is_found(self):
        store = _store(_mem("我喜欢深烘咖啡每天早上"))
        assert store.search_text("alice", "shared", "深烘咖啡", 10)

    def test_a_term_that_is_absent_matches_nothing(self):
        store = _store(_mem("我喜欢深烘咖啡"))
        assert store.search_text("alice", "shared", "红茶", 10) == []

    def test_an_empty_query_matches_nothing(self):
        assert _store(_mem("anything")).search_text("alice", "shared", "  ", 10) == []

    def test_another_namespace_is_not_searched(self):
        store = _store(_mem("orion", ns="elsewhere"))
        assert store.search_text("alice", "shared", "orion", 10) == []

    def test_a_private_namespace_is_invisible_to_other_users(self):
        store = _store(_mem("orion", user="alice", ns="private"))
        assert store.search_text("bob", "private", "orion", 10) == []
        assert store.search_text("alice", "private", "orion", 10)

    def test_a_shared_namespace_is_visible_to_everyone(self):
        store = _store(_mem("orion", user="alice", ns="shared"))
        assert store.search_text("bob", "shared", "orion", 10)

    def test_an_unconfirmed_media_memory_is_hidden(self):
        store = _store(_mem("orion photo", confirmed=False))
        assert store.search_text("alice", "shared", "orion", 10) == []

    def test_results_are_sliced_by_offset_and_limit(self):
        store = _store(*[_mem(f"orion {i}") for i in range(5)])
        page1 = store.search_text("alice", "shared", "orion", 2, 0)
        page2 = store.search_text("alice", "shared", "orion", 2, 2)
        assert len(page1) == len(page2) == 2
        assert {h.id for h in page1}.isdisjoint({h.id for h in page2})

    def test_hits_carry_a_score(self):
        store = _store(_mem("orion"))
        assert store.search_text("alice", "shared", "orion", 10)[0].score is not None


class TestRrfFusion:
    def test_a_row_in_both_lists_beats_the_top_of_only_one(self):
        x, y, z = _mem("x", mid="x"), _mem("y", mid="y"), _mem("z", mid="z")
        fused = rrf_fuse([[x, y], [y, z]])
        assert [m.id for m in fused] == ["y", "x", "z"]

    def test_the_score_is_the_sum_of_reciprocal_ranks(self):
        a = _mem("a", mid="a")
        fused = rrf_fuse([[a], [a]], k=60)
        assert fused[0].score == pytest.approx(2 / 61)

    def test_a_row_is_returned_once(self):
        a = _mem("a", mid="a")
        assert len(rrf_fuse([[a], [a], [a]])) == 1

    def test_ties_keep_first_appearance_order(self):
        a, b = _mem("a", mid="a"), _mem("b", mid="b")
        assert [m.id for m in rrf_fuse([[a], [b]])] == ["a", "b"]

    def test_empty_rankings_fuse_to_nothing(self):
        assert rrf_fuse([]) == []
        assert rrf_fuse([[], []]) == []

    def test_the_inputs_are_not_mutated(self):
        a = _mem("a", mid="a")
        rrf_fuse([[a]])
        assert a.score is None


class _FakeRetriever:
    """Returns a fixed ranking and records how it was called."""

    def __init__(self, ranking):
        self.ranking, self.calls = ranking, []

    def search(self, user_id, query, namespace, limit, offset=0):
        self.calls.append((limit, offset))
        return self.ranking[offset : offset + limit]


class TestHybridRetriever:
    def test_each_leg_is_asked_for_more_than_is_returned(self):
        """The fused top-N can hold a vector rank-12 and a keyword rank-3, so a
        leg asked for only N would never offer the row that belongs."""
        vec, kw = _FakeRetriever([]), _FakeRetriever([])
        HybridRetriever(vec, kw, depth_factor=5).search("u", "q", "ns", limit=8)
        assert vec.calls == [(40, 0)] and kw.calls == [(40, 0)]

    def test_both_legs_start_from_rank_zero_even_when_paging(self):
        """A fused rank depends on a row's place in BOTH lists, so each leg is
        fused whole and the page is sliced afterwards."""
        vec, kw = _FakeRetriever([]), _FakeRetriever([])
        HybridRetriever(vec, kw, depth_factor=5).search("u", "q", "ns", 4, offset=8)
        assert vec.calls == [(60, 0)] and kw.calls == [(60, 0)]

    def test_pages_are_disjoint_and_ordered(self):
        rows = [_mem(str(i), mid=str(i)) for i in range(10)]
        hybrid = HybridRetriever(_FakeRetriever(rows), _FakeRetriever(rows[::-1]))
        p1 = hybrid.search("u", "q", "ns", 4, 0)
        p2 = hybrid.search("u", "q", "ns", 4, 4)
        assert {m.id for m in p1}.isdisjoint({m.id for m in p2})
        assert [m.score for m in p1 + p2] == sorted(
            (m.score for m in p1 + p2), reverse=True
        )


@pytest.fixture
def svc() -> MemoryService:
    return MemoryService(build_context())


class TestRecallModes:
    def test_the_default_is_still_similarity(self, svc):
        svc.remember("alice", "alpha")
        svc.remember("alice", "beta")
        assert svc.recall("alice", "alpha") == svc.recall(
            "alice", "alpha", mode="similarity"
        )

    def test_keyword_returns_only_hits_where_similarity_ranks_everything(self, svc):
        for text in ("alpha one", "beta two", "gamma three"):
            svc.remember("alice", text)
        keyword = svc.recall("alice", "alpha", mode="keyword")
        similarity = svc.recall("alice", "alpha", mode="similarity")
        assert len(keyword["items"]) == 1
        assert len(similarity["items"]) == 3

    def test_rrf_finds_an_exact_hit(self, svc):
        for text in ("alpha one", "beta two", "gamma three"):
            svc.remember("alice", text)
        items = svc.recall("alice", "alpha", mode="rrf")["items"]
        assert items[0]["content"] == "alpha one"

    def test_an_unknown_mode_names_the_valid_ones(self, svc):
        with pytest.raises(ValueError, match="similarity, keyword, rrf"):
            svc.recall("alice", "x", mode="fuzzy")

    def test_total_is_the_pool_searched_not_the_hit_count(self, svc):
        for text in ("alpha", "beta", "gamma"):
            svc.remember("alice", text)
        assert svc.recall("alice", "alpha", mode="keyword")["total"] == 3

    def test_has_more_is_true_only_when_another_page_exists(self, svc):
        for i in range(3):
            svc.remember("alice", f"alpha {i}")
        for i in range(5):  # non-matching rows must not make has_more lie
            svc.remember("alice", f"beta {i}")
        p1 = svc.recall("alice", "alpha", limit=2, mode="keyword")
        assert (len(p1["items"]), p1["has_more"], p1["next_cursor"]) == (2, True, "2")
        p2 = svc.recall("alice", "alpha", limit=2, cursor="2", mode="keyword")
        assert (len(p2["items"]), p2["has_more"], p2["next_cursor"]) == (1, False, None)

    def test_a_result_that_fits_one_page_has_no_next_page(self, svc):
        """The bug `_page` would have had here: 1 hit in a pool of 8 reads as
        `has_more` because 1 < 8, and the caller is sent to an empty page."""
        svc.remember("alice", "alpha")
        for i in range(7):
            svc.remember("alice", f"beta {i}")
        out = svc.recall("alice", "alpha", limit=5, mode="keyword")
        assert out["has_more"] is False and out["next_cursor"] is None

    def test_each_mode_is_routed_to_its_own_retriever(self, svc):
        sim, kw, hy = (_FakeRetriever([]) for _ in range(3))
        ctx = replace(svc.ctx, retriever=sim, retrievers={"keyword": kw, "rrf": hy})
        routed = MemoryService(ctx)
        routed.recall("alice", "q", limit=3, mode="keyword")
        routed.recall("alice", "q", limit=3, mode="rrf")
        routed.recall("alice", "q", limit=3)
        # keyword and rrf over-fetch by one to learn whether there is a next page
        assert kw.calls == [(4, 0)] and hy.calls == [(4, 0)]
        assert sim.calls == [(3, 0)]

    def test_a_mode_missing_from_the_context_is_refused(self, svc):
        routed = MemoryService(replace(svc.ctx, retrievers={}))
        with pytest.raises(ValueError, match="not available"):
            routed.recall("alice", "q", mode="keyword")
