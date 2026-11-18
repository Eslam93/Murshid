# Tamper-evident records: a decision commits to a hash of the exact version

An approval, a signature or any other decision stores the digest of the exact content it was made
on. Later, `matches` says whether the record still has that content: an approved request that was
changed afterwards no longer matches its approval, and the trail can show it.

## How to call it

```python
from toolkit.tamper_evident.core import canonical_json, digest, matches

decided_on = {"title": request.title, "total": request.total, "lines": [...]}  # what counts
approval.version_digest = digest(decided_on)  # "sha256:<64 hex>"
...
still_valid = matches(current_content_of(request), approval.version_digest)
```

- `canonical_json(value)`: one byte string per content. Keys sorted, no spaces, UTF-8. A `Decimal`
  is written normalised (`1.50` and `1.5` are one value), dates and times as ISO 8601 (a time must
  carry its timezone), UUIDs and enums as text.
- A float is refused: it has no single exact text. So is a set, whose order is not defined.
- `digest(value)`: `sha256:` and the hex SHA-256 of the canonical form. `matches` compares in
  constant time.

## When lifting, change

Nothing in the core. Choose, in your adapter, exactly which fields a decision covers: a field left
out can change without breaking the match, and a field put in (an updated-at time) breaks it for
every edit. Keep the test that pins a fixed record's digest: it is what tells you a change to the
canonical form would invalidate every stored digest.

Needs: the standard library. Tests: `toolkit/tamper_evident/tests/`.
