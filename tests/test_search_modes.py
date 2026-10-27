"""Search modes (#17): similarity, keyword, and rrf.

The properties worth pinning are the ones a user would be hurt by: keyword mode
must find an exact string and ONLY rows containing it, and `has_more` must not
promise a page that comes back empty.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from polymnemo.context import build_context
from polymnemo.models import Memory, new_id
from polymnemo.retriever import HybridRetriever, rrf_fuse
from polymnemo.retriever.hybrid import RRF_DEPTH
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

    def test_a_term_that_is_absent_matches_nothing(self):
        store = _store(_mem("I prefer dark roast coffee"))
        assert store.search_text("alice", "shared", "tea", 10) == []

    def test_an_id_inside_punctuation_is_found(self):
        """Why keyword mode is substring rather than tokens: the point is an ID
        or an error string, which is not delimited like a word."""
        store = _store(_mem("request failed: order_id=88312&retry=3"))
        assert store.search_text("alice", "shared", "88312", 10)

    def test_a_tighter_match_ranks_first(self):
        """The ordering PostgresStore's similarity() also gives: a chunk the
        query dominates beats one it is lost in. Pinned here because the two
        stores once ranked these differently and nothing noticed."""
        store = _store(_mem("orion"), _mem("orion " + "padding " * 30))
        hits = store.search_text("alice", "shared", "orion", 10)
        assert hits[0].content == "orion"
        assert hits[0].score > hits[1].score

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


class _Leg:
    """A leg whose ranking is fixed and which can be read to any depth."""

    def __init__(self, ids):
        self.rows = [_mem(i, mid=i) for i in ids]

    def search(self, user_id, query, namespace, limit, offset=0):
        return self.rows[offset : offset + limit]


class TestHybridRetriever:
    def test_each_leg_is_asked_for_more_than_is_returned(self):
        """The fused top-N can hold a vector rank-12 and a keyword rank-3, so a
        leg asked for only N would never offer the row that belongs."""
        vec, kw = _FakeRetriever([]), _FakeRetriever([])
        HybridRetriever(vec, kw).search("u", "q", "ns", limit=8)
        assert vec.calls == [(RRF_DEPTH, 0)] and kw.calls == [(RRF_DEPTH, 0)]
        assert RRF_DEPTH > 8

    def test_every_page_reads_the_legs_to_the_same_depth(self):
        """Not (offset+limit) * factor, which is what this used to assert. That
        made page 2 fuse a different candidate set from page 1, and was the bug."""
        vec, kw = _FakeRetriever([]), _FakeRetriever([])
        hybrid = HybridRetriever(vec, kw)
        for offset in (0, 8, 16, 100):
            hybrid.search("u", "q", "ns", limit=8, offset=offset)
        assert {c for c in vec.calls} == {(RRF_DEPTH, 0)}
        assert {c for c in kw.calls} == {(RRF_DEPTH, 0)}

    def test_a_page_larger_than_the_window_is_not_silently_truncated(self):
        vec, kw = _FakeRetriever([]), _FakeRetriever([])
        HybridRetriever(vec, kw).search("u", "q", "ns", limit=RRF_DEPTH * 2)
        assert vec.calls == [(RRF_DEPTH * 2, 0)]

    def test_rows_past_the_window_are_not_reachable_by_paging(self):
        """The price of stable paging. A row ranked beyond the window in BOTH
        legs never appears, however far the cursor is followed. Paged in small
        steps, because a single page larger than the window widens it."""
        deep = [f"r{i}" for i in range(RRF_DEPTH + 20)]
        hybrid = HybridRetriever(_Leg(deep), _Leg(deep))
        seen: list[str] = []
        offset = 0
        while page := hybrid.search("u", "q", "ns", 10, offset):
            seen.extend(m.id for m in page)
            offset += 10
        assert seen == deep[:RRF_DEPTH]

    def test_paging_never_repeats_or_skips_a_row(self):
        """The case the reviewer found on #172. X is vector rank 1; Y is vector
        rank 6 AND keyword rank 11. If page 1 reads each leg 10 deep it never
        sees Y's keyword rank, and page 2 reading 15 deep does -- so the fused
        order changes between pages and X is returned twice while Y is lost.

        The legs here return a FIXED ranking and only differ in how deep they
        are read, which is what a real store does and what the older fakes in
        this file could not express."""
        vec = _Leg(["X", "a1", "a2", "a3", "a4", "Y"] + [f"v{i}" for i in range(30)])
        kw = _Leg([f"k{i}" for i in range(10)] + ["Y"] + [f"w{i}" for i in range(30)])
        hybrid = HybridRetriever(vec, kw)

        # MemoryService.recall asks for limit+1 to learn whether another page
        # exists, then keeps `limit`. limit=1 here, so it asks for 2.
        pages = [hybrid.search("u", "q", "ns", 2, offset)[0].id for offset in range(8)]

        assert len(set(pages)) == len(pages), f"a row came back twice: {pages}"
        one_shot = [m.id for m in hybrid.search("u", "q", "ns", 8, 0)]
        assert pages == one_shot, "paging disagrees with fetching the same rows at once"

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

    @pytest.mark.parametrize("mode", ["keyword", "rrf"])
    def test_following_the_cursor_returns_each_hit_exactly_once(self, svc, mode):
        """What a client actually does: page until has_more is false."""
        for i in range(13):
            svc.remember("alice", f"alpha item {i}")
        for i in range(6):
            svc.remember("alice", f"beta item {i}")

        seen: list[str] = []
        cursor = None
        for _ in range(10):  # a bound, so a broken cursor fails rather than hangs
            out = svc.recall("alice", "alpha", limit=5, cursor=cursor, mode=mode)
            seen.extend(i["id"] for i in out["items"])
            if not out["has_more"]:
                break
            cursor = out["next_cursor"]
        else:
            pytest.fail("the cursor never ran out")

        assert len(seen) == len(set(seen)), "a row was returned on two pages"
        # keyword returns exactly the 13 hits; rrf also returns the beta rows,
        # which similarity ranks, so only the alpha rows are required here
        alpha = {
            i["id"]
            for i in svc.list_memories("alice", limit=100)["items"]
            if "alpha" in i["content"]
        }
        assert alpha <= set(seen)

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
