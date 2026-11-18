# Determinism, golden-file and invariant tests

Test helpers for code whose output must not drift: a matching engine, a forecast, a report. Check
that the same input always gives the same result, also with its rows in another order; compare a
result with a committed JSON file (and rewrite the file on purpose with `GOLDEN_UPDATE=1`); and
name the rules a result breaks.

## How to call it

```python
from toolkit.golden_tests.core import (
    Golden,
    assert_deterministic,
    assert_order_independent,
    broken_invariants,
)

GOLDEN = Golden(Path(__file__).parent / "golden")


def test_matching_is_stable() -> None:
    result = assert_deterministic(match, invoice, order, receipt)
    assert_order_independent(lambda lines: match_lines(lines, order), invoice.lines)
    GOLDEN.check("partial_receipt", result)
    assert (
        broken_invariants(
            result,
            {
                "matched amounts add up to the invoice total": lambda r: sum(r.amounts) == r.total,
            },
        )
        == []
    )
```

## Seams

- `canonical_json(value)`: sorted keys, decimals as exact text, dates in ISO form, UUIDs as text,
  dataclasses as objects, sets sorted; the form every comparison uses.
- `assert_order_independent(function, items, runs=5, seed=0)`: the function takes the list.
- `Golden(folder, env=...)`: a failing check prints a unified diff of the first lines.
- `broken_invariants(value, rules)`: a rule that raises counts as broken.

## When lifting, change

Nothing. Commit the golden folder beside the tests, and review a rewritten golden file like code.

Needs: the standard library. Tests: `toolkit/golden_tests/tests/`.
