"""Query-result Redis cache key builder.

Key format: user:{user_id}:{sha256(normalized_question + "|" + sorted_roles)}

Including user_id enables O(K) bulk deletion on role changes:
    redis.scan_match("user:{user_id}:*") + bulk delete

Including roles in the hash ensures correctness when visibility enforcement
produces different KG context (and thus different answers) per role combination.
"""
import hashlib
import re


def build_cache_key(user_id: str, question: str, roles: list[str]) -> str:
    normalized = re.sub(r"\s+", " ", question.lower().strip())
    roles_part = "|".join(sorted(roles))
    content = f"{normalized}|{roles_part}"
    digest = hashlib.sha256(content.encode()).hexdigest()
    return f"user:{user_id}:{digest}"
