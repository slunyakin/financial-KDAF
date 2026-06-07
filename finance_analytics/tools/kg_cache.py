"""KG context Redis cache helpers.

Separate from the query-result cache (tools/cache_key.py):
  - Key prefix: "kg:"
  - TTL: 5 minutes (300 seconds)
  - Invalidated when any of KG_INVALIDATION_LABELS nodes are written

Key format: kg:{sha256(sorted_domain_terms + "|" + sorted_user_roles)}

user_roles is included so that future visibility enforcement produces separate
cache entries per role combination. In v1, KG is world-readable — all roles
get the same context — but the key structure is forward-compatible.
"""
import hashlib

KG_CACHE_TTL: int = 300  # seconds

# Node labels that invalidate the entire KG context cache on write
KG_INVALIDATION_LABELS: frozenset[str] = frozenset([
    "BusinessRule",
    "KnownAnomaly",
    "Covenant",
    "LaborContract",
    "LaborRate",
    "CostOfCapital",
])


def kg_cache_key(domain_terms: list[str], user_roles: list[str]) -> str:
    terms_part = "|".join(sorted(domain_terms))
    roles_part = "|".join(sorted(user_roles))
    content = f"{terms_part}|{roles_part}"
    return f"kg:{hashlib.sha256(content.encode()).hexdigest()}"


def should_invalidate_kg_cache(node_label: str) -> bool:
    """True if writing a node of this label must flush the KG context cache."""
    return node_label in KG_INVALIDATION_LABELS
