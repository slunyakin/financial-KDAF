"""Unit tests for cache key builders.

Validates correctness, determinism, and key separation properties
without any Redis or network dependency.
"""
from finance_analytics.tools.cache_key import build_cache_key
from finance_analytics.tools.kg_cache import KG_INVALIDATION_LABELS, kg_cache_key


# ── Query-result cache key ────────────────────────────────────────────────────

class TestBuildCacheKey:
    def test_same_inputs_produce_same_key(self) -> None:
        k1 = build_cache_key("u1", "What was Q3 margin?", ["analyst"])
        k2 = build_cache_key("u1", "What was Q3 margin?", ["analyst"])
        assert k1 == k2

    def test_key_format(self) -> None:
        key = build_cache_key("u1", "question", ["analyst"])
        parts = key.split(":")
        assert parts[0] == "user"
        assert parts[1] == "u1"
        assert len(parts[2]) == 64  # SHA-256 hex digest

    def test_different_users_different_keys(self) -> None:
        k1 = build_cache_key("u1", "same question", ["analyst"])
        k2 = build_cache_key("u2", "same question", ["analyst"])
        assert k1 != k2

    def test_different_roles_different_keys(self) -> None:
        k1 = build_cache_key("u1", "same question", ["analyst"])
        k2 = build_cache_key("u1", "same question", ["knowledge_engineer"])
        assert k1 != k2

    def test_role_order_does_not_matter(self) -> None:
        k1 = build_cache_key("u1", "q", ["analyst", "viewer"])
        k2 = build_cache_key("u1", "q", ["viewer", "analyst"])
        assert k1 == k2

    def test_question_normalisation(self) -> None:
        # Extra whitespace and casing should produce the same key
        k1 = build_cache_key("u1", "What was Q3 margin?", ["analyst"])
        k2 = build_cache_key("u1", "  what was q3 margin?  ", ["analyst"])
        assert k1 == k2


# ── KG context cache key ─────────────────────────────────────────────────────

class TestKgCacheKey:
    def test_key_prefix(self) -> None:
        key = kg_cache_key(["margin", "APAC"], ["analyst"])
        assert key.startswith("kg:")

    def test_deterministic(self) -> None:
        k1 = kg_cache_key(["margin", "APAC"], ["analyst"])
        k2 = kg_cache_key(["margin", "APAC"], ["analyst"])
        assert k1 == k2

    def test_term_order_does_not_matter(self) -> None:
        k1 = kg_cache_key(["margin", "APAC"], ["analyst"])
        k2 = kg_cache_key(["APAC", "margin"], ["analyst"])
        assert k1 == k2

    def test_different_terms_different_keys(self) -> None:
        k1 = kg_cache_key(["margin"], ["analyst"])
        k2 = kg_cache_key(["covenant"], ["analyst"])
        assert k1 != k2

    def test_different_roles_different_keys(self) -> None:
        k1 = kg_cache_key(["margin"], ["analyst"])
        k2 = kg_cache_key(["margin"], ["knowledge_engineer"])
        assert k1 != k2


# ── KG cache invalidation labels ─────────────────────────────────────────────

class TestKgInvalidationLabels:
    def test_all_required_labels_present(self) -> None:
        required = {
            "BusinessRule", "KnownAnomaly", "Covenant",
            "LaborContract", "LaborRate", "CostOfCapital",
        }
        assert required <= KG_INVALIDATION_LABELS

    def test_non_invalidating_labels_excluded(self) -> None:
        # Writes to these should NOT flush the KG context cache
        for label in ("Table", "Column", "Segment", "Ledger", "Question"):
            assert label not in KG_INVALIDATION_LABELS
