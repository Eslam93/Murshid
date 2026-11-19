# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""A bench run's spend on model calls, metered call by call, with a cap no new call may cross.

`MeteredProvider` wraps an answering provider or a judge. Before each call it asks the
`SpendMeter` whether the call may start: with a cap set, a call is refused (`SpendCapError`)
once the logged spend plus the most expensive single call so far would pass the cap, so the
run stops short of the cap rather than after it. After each call the meter adds the call's
cost, priced by the provider itself from the registry's dated price tables, and appends one row
to the run's spend log. Zero-key providers cost nothing and log nothing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from murshid.providers.base import LLMProvider, ProviderResponse

# Before the first paid call the meter has no call to go by; it reserves this much instead.
FIRST_CALL_RESERVE_USD = 0.01


class SpendCapError(RuntimeError):
    """A metered call would take the run's logged spend past its cap."""


class SpendMeter:
    """The run's logged spend, its cap (None for no cap), and the log of every paid call."""

    def __init__(self, cap_usd: float | None, log_path: Path | None = None) -> None:
        if cap_usd is not None and cap_usd <= 0:
            raise ValueError("the spend cap must be a positive number of USD")
        self.cap_usd = cap_usd
        self.log_path = log_path
        self.spent_usd = 0.0
        self.largest_call_usd = 0.0
        self.paid_calls = 0
        self.stopped = False

    def check(self) -> None:
        """Refuse the next call when it could take the logged spend past the cap."""
        if self.cap_usd is None:
            return
        reserve = self.largest_call_usd or FIRST_CALL_RESERVE_USD
        if self.stopped or self.spent_usd + reserve > self.cap_usd:
            self.stopped = True
            raise SpendCapError(
                f"spend cap of ${self.cap_usd:.2f} reached: ${self.spent_usd:.4f} logged, "
                f"and the next call could cost up to ${reserve:.4f}"
            )

    def record(self, provider: LLMProvider, response: ProviderResponse) -> float:
        """Add one call's cost and log it; returns the cost."""
        cost = provider.cost_estimate_usd(response)
        if cost <= 0:
            return 0.0
        self.spent_usd += cost
        self.largest_call_usd = max(self.largest_call_usd, cost)
        self.paid_calls += 1
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "provider": provider.name,
                "model_id": provider.model_id,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": round(cost, 8),
                "spent_usd": round(self.spent_usd, 8),
            }
            with self.log_path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(row) + "\n")
        return cost

    def summary(self) -> dict[str, Any]:
        """What the run manifest records about the spend."""
        return {
            "spent_usd": round(self.spent_usd, 6),
            "cap_usd": self.cap_usd,
            "cap_reached": self.stopped,
            "paid_calls": self.paid_calls,
        }


class MeteredProvider:
    """A provider whose every call is checked against, then added to, a spend meter."""

    def __init__(self, inner: LLMProvider, meter: SpendMeter) -> None:
        self.inner = inner
        self.meter = meter
        self.name = inner.name
        self.model_id = inner.model_id

    def is_available(self) -> bool:
        return self.inner.is_available()

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        return self.inner.cost_estimate_usd(response)

    def generate(
        self, system: str, user: str, max_tokens: int = 1024, timeout: float = 30.0
    ) -> ProviderResponse:
        self.meter.check()
        response = self.inner.generate(system, user, max_tokens=max_tokens, timeout=timeout)
        self.meter.record(self.inner, response)
        return response
