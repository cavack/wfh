from waterfallhunter import main


def test_runtime_lifecycle_decision_clock_is_taken_after_sources(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        main.time,
        "time",
        lambda: 1000.75,
    )

    evidence = main._build_runtime_lifecycle_v2_evidence(
        metrics={
            "microstructure": {
                "observed_at": 1000.60,
            },
        },
        analysis_observed_at=1000.10,
        reference_observed_at=999.50,
    )

    assert evidence.decision_at == 1001
    assert max(evidence.required_observed_at) <= evidence.decision_at
