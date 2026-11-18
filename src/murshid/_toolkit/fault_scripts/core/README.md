# Scripted faults and ablation checks for tests

Two test tools. `ScriptedTransport` goes under a real `httpx.AsyncClient` and answers each request
from a script: a response (a 429 with Retry-After, a 503), an error of the client's own class
built with the real request (`httpx.ConnectError`, `httpx.ReadTimeout`), or a delay before either.
`assert_ablation_flips` proves a test tests something: its check must pass with a component in
place and fail with the component removed.

## How to call it

```python
import httpx
from toolkit.fault_scripts.core import ScriptedTransport, fault, respond

transport = ScriptedTransport(
    [
        respond(429, headers={"Retry-After": "1"}),
        fault(httpx.ConnectError),
        respond(200, json={"ok": True}),
    ]
)
async with httpx.AsyncClient(transport=transport, base_url="https://upstream.test") as http:
    result = await code_under_test(http)
assert len(transport.requests) == 3
```

```python
from toolkit.fault_scripts.core import ablated, assert_ablation_flips

await assert_ablation_flips(
    lambda: guarded_reply_is_refused(),  # true with the guard
    lambda: ablated(guards, "sanitize", lambda text: text),  # the guard removed
)
```

## Seams

- A step may also be a function of the request, for an answer that depends on what was sent.
- `ScriptExhaustedError` is raised when the code makes more calls than the script has steps, so a
  surprise retry fails the test.
- `delay(seconds, then)` runs into the caller's timeout when `seconds` is longer.

## When lifting, change

Nothing. For a client that is not httpx, build its own error classes the same way: the fake must
raise what the real client raises, from where it raises it.

Needs: httpx. Tests: `toolkit/fault_scripts/tests/`.
