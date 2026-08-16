# Channel-replication research

## Scope

This project reproduces observable, testable trading behaviour from the supplied
channel exports. It does not reuse channel copy, represent channel claims as
verified results, or enable automated execution.

## Evidence available on 2026-08-09

- 152 exported LBank USDT-perpetual short signals.
- Reported leverage: 3x in 90 records, 4x in 54, 2x in 5, and missing in 3.
- Signal language primarily identifies an existing bearish state. The export has
  very few explicit pullback references, so a failed pullback cannot be the sole
  valid setup.
- A separate 41-event, 24-hour market reconstruction reports 26 positive net
  outcomes after its stated fee and slippage assumptions (63.41%). This is an
  external reference dataset, not ground truth for this system.
- Its 72-hour TP/SL sensitivity table reports higher in-sample hit rates for
  5% TP and 10% or 15% SL, but labels every row `sensitivity_only_not_optimized`.

## Reconstructed setup taxonomy

The model is short-bias and only studies USDT-settled perpetuals. The three
exclusive setup types are:

1. `FAILED_PULLBACK`: 4h support is broken, price retests it, and the retest
   closes below the zone with a lower high.
2. `BREAKDOWN`: a 4h support break has bearish close and volume expansion.
3. `CONTINUATION`: after 4h structural damage, the 1h bounce makes a lower
   high and bears regain control.

All require a persisted Hype Watch context, 4h damage, and a 15m/5m bearish
entry trigger. A live `SHORT_READY` additionally requires fresh LBank price,
spread, depth, filters, and a positive fee-adjusted plan. Missing live inputs
are a rejection, never an assumed value.

## Research constraints

- Historical OHLCV is official Binance USD-M data only; archives are preferred
  and REST is used only to fill an unavailable partial archive month.
- Historical LBank order book, funding, and OI are not fabricated. An OHLCV
  replay therefore tests price-path logic only and cannot certify execution.
- Parameter selection is allowed only on the train segment. Validation and
  holdout are time-based, with the holding horizon purged at boundaries.
- A current symbol snapshot is not a point-in-time historical universe and is
  explicitly marked as survivor-biased.

## Acceptance gate for any live promotion

All must hold before changing live score gates or signal behaviour:

1. At least 100 settled trades across a point-in-time universe.
2. At least 30 settled holdout trades.
3. Positive expectancy after documented, real execution costs.
4. Holdout win rate and signal density meet the declared target without a
   parameter change after inspecting holdout.
5. No missing LBank execution inputs for a signal promoted beyond `WATCH`.

Current status: `TESTING`; no setup has met the acceptance gate.
