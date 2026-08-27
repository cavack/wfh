---
name: scientific-backtest-validation
description: Use when evaluating WaterfallHunter strategy evidence, backtests, walk-forward results, holdout performance, leakage risk, parameter stability, regime robustness, uncertainty, or promotion readiness.
---

# WFH Scientific Backtest & Model Validation

## Overview

Evaluate whether WaterfallHunter strategy changes have robust out-of-sample evidence. Protect time ordering and untouched evaluation data from selection pressure.

## When to Use

Use for backtests, replay equivalence, walk-forward, holdout, calibration, leakage, embargo, bootstrap uncertainty, regime robustness, concentration, sensitivity, parameter search, or promotion decisions.

## Scope

Own point-in-time correctness, train/development/calibration/holdout separation, embargo, walk-forward protocol, block/bootstrap uncertainty, regime stratification, concentration guards, PF/EV/MDD/MAE/MFE, sensitivity, parameter stability, multiple-testing/selection bias, and promotion evidence.

The holdout is not an iterative tuning set.

## Workflow

1. Establish data provenance, timestamp semantics, survivorship/universe rules, and feature availability at decision time.
2. Reconstruct the full model-selection history. If the reported holdout influenced prior parameter choices, treat that holdout as contaminated and require a new untouched evaluation set or future forward evidence.
3. Define development/calibration/walk-forward windows and embargo before looking at final evaluation results.
4. Evaluate returns including realistic costs/slippage assumptions and report PF, EV, drawdown, win rate, MAE/MFE, sample count, and concentration together.
5. Quantify uncertainty with appropriate bootstrap/block methods and check regime/symbol concentration.
6. Run parameter-neighborhood/sensitivity checks; prefer stable plateaus to isolated optima.
7. Compare candidate versus baseline without using final holdout to iterate.
8. Issue a promotion disposition with explicit unmet gates and uncertainty.

## Evidence and Readiness

Strong headline metrics are insufficient. Repeated searches inflate selection bias. A contaminated holdout cannot certify promotion, even if performance is excellent. State `PROPOSAL`, `NOT_SUPPORTED`, or evidence-backed promotion recommendation without implying production deployment authority.

## Verification

Check point-in-time features, no lookahead, embargo, split integrity, untouched final evaluation, sample sufficiency, transaction-cost assumptions, bootstrap method, regime/concentration results, parameter stability, and reproducibility hashes/manifests where supported.

## Handoffs

Decision-logic changes → `strategy-score-lifecycle`. Raw data quality → `market-data-evidence-quality`. Reproducible test execution → `verification-regression`. Deployment gating → `release-production-certification`.

## Common Mistakes

- Tuning on the holdout after seeing its performance.
- Reporting win rate without PF/EV/drawdown/sample context.
- Ignoring symbol/regime concentration.
- Optimizing a single sharp parameter optimum.
- Treating a backtest as proof of live execution realizability.
