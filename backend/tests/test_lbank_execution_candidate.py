from waterfallhunter.core.lbank_execution_candidate import (
    LBankExecutionCandidateEnricher,
)


class FakeStats:
    def __init__(
        self,
        summary,
    ):
        self.summary = summary
        self.calls = 0

    def summarize_symbol(
        self,
        symbol,
    ):
        self.calls += 1

        result = dict(
            self.summary
        )

        result[
            "symbol"
        ] = symbol

        return result


def suitable_summary():
    return {
        "symbol": "TEST/USDT:USDT",
        "availability_rate": 1.0,
        "evidence": {
            "status": "SUFFICIENT",
            "observed_samples": 37,
            "observation_span_hours": 38.0,
        },
        "metrics": {
            "spread_pct": {
                "p90": 0.05,
            },
            "cost_100_pct": {
                "p90": 0.08,
            },
            "depth_25bps_min_usdt": {
                "p50": 10_000.0,
            },
        },
    }


def test_candidate_enricher_exposes_compact_suitable_packet():
    stats = FakeStats(
        suitable_summary()
    )

    enricher = (
        LBankExecutionCandidateEnricher(
            stats=stats,
        )
    )

    result = enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    assert (
        result["status"]
        == "SUITABLE"
    )

    assert (
        result[
            "evidence_status"
        ]
        == "SUFFICIENT"
    )

    assert (
        result[
            "observed_samples"
        ]
        == 37
    )

    assert (
        result[
            "observation_span_hours"
        ]
        == 38.0
    )

    assert (
        result[
            "cost_100_p90_pct"
        ]
        == 0.08
    )

    assert (
        result[
            "spread_p90_pct"
        ]
        == 0.05
    )

    assert (
        result[
            "depth_25bps_p50_usdt"
        ]
        == 10_000.0
    )

    assert (
        result[
            "observational_only"
        ]
        is True
    )

    assert (
        result[
            "trade_eligible"
        ]
        is None
    )


def test_insufficient_evidence_is_exposed_as_unknown():
    data = suitable_summary()

    data[
        "evidence"
    ][
        "status"
    ] = "INSUFFICIENT"

    stats = FakeStats(
        data
    )

    enricher = (
        LBankExecutionCandidateEnricher(
            stats=stats,
        )
    )

    result = enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    assert (
        result["status"]
        == "UNKNOWN"
    )

    assert (
        result[
            "evidence_status"
        ]
        == "INSUFFICIENT"
    )


def test_candidate_enricher_cache_prevents_repeated_stats_reads():
    stats = FakeStats(
        suitable_summary()
    )

    enricher = (
        LBankExecutionCandidateEnricher(
            stats=stats,
            cache_ttl_seconds=60.0,
        )
    )

    first = enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    second = enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    assert first == second

    assert (
        stats.calls
        == 1
    )


def test_cached_packet_is_returned_as_a_copy():
    stats = FakeStats(
        suitable_summary()
    )

    enricher = (
        LBankExecutionCandidateEnricher(
            stats=stats,
        )
    )

    first = enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    first[
        "status"
    ] = "CORRUPTED"

    second = enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    assert (
        second["status"]
        == "SUITABLE"
    )


def test_invalidate_symbol_forces_refresh():
    stats = FakeStats(
        suitable_summary()
    )

    enricher = (
        LBankExecutionCandidateEnricher(
            stats=stats,
        )
    )

    enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    assert (
        stats.calls
        == 1
    )

    enricher.invalidate(
        "TEST/USDT:USDT"
    )

    enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    assert (
        stats.calls
        == 2
    )


def test_unexpected_stats_failure_returns_safe_unknown():
    class BrokenStats:
        def summarize_symbol(
            self,
            symbol,
        ):
            raise RuntimeError(
                "boom"
            )

    enricher = (
        LBankExecutionCandidateEnricher(
            stats=BrokenStats(),
        )
    )

    result = enricher.for_symbol(
        "TEST/USDT:USDT"
    )

    assert (
        result["status"]
        == "UNKNOWN"
    )

    assert (
        result[
            "observational_only"
        ]
        is True
    )

    assert (
        result[
            "trade_eligible"
        ]
        is None
    )
