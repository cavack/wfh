# Wave 1D — Probability Cleanup, Freshness Contracts, and Strict Calibration Filtering

Status: DESIGN DRAFT — implementation is not authorized by this document alone.

Date: 2026-08-20

Base: Wave 1C certified development head `402fed74e27abd00163ec5a8e3bd27b30001a5ec`

Umbrella: Final Design v6.1 workstreams P1-D, P1-E, and P1-F.

## 1. Purpose

Wave 1D closes the remaining semantic correctness gaps between Wave 1C cohort purity and the typed Product Layer.

It has three independently reviewable boundaries:

1. **P1-D Probability Cleanup** — remove the misleading `tp_24h_probability` proxy from decision, ranking, dashboard-facing, and Telegram-facing semantics.
2. **P1-E Freshness Contracts** — make analysis freshness and reference-price freshness independent, explicit, reproducible, and fail-closed.
3. **P1-F Strict Outcome / Calibration Filtering** — make every production-facing outcome/calibration input STRICT-only by default with explicit cohort and lineage provenance.

These three workstreams converge before P2 Typed API. They do not create, fit, recalibrate, or promote a predictive probability model or a scientifically promoted Final Signal Score.

## 2. Source-of-truth constraints

This design follows Final Design v6.1, the consolidated Product Requirements, the Production Baseline Audit, and the canonical GitHub source:

- Final Design G7: default production calibration/report scope is `signal_class=STRICT`; EXPERIMENTAL outcomes must never leak into strict aggregates.
- Final Design G8: no decision/ranking/dashboard/Telegram reference to `tp_24h_probability`.
- Final Design dependency graph: P1-D, P1-E, and P1-F follow P1-C and converge before P2 Typed API.
- Final Design / Product Requirements: Evidence Quality, Predictive Evidence Score, Final Signal Score, Execution Risk, and Calibrated Outcome Layer are separate concepts.
- Evidence Quality is not directional predictive evidence.
- Audit finding: `FinalRanking` currently reads `tp_24h_probability`, calls it `empirical_probability`, and assigns 10 ranking points.
- Audit finding: Telegram still renders the same metric as `TP 24h: xx%`.
- Product requirement F-10: the current metric is an unconditional 24h downside hit-rate, not signal success probability.
- Product requirement F-13 / AC-17: analysis freshness and reference freshness must be independent.
- Product requirement F-14 / AC-18: ScoreV2 / Final Signal Score is an evidence/prioritization score, not probability.

### 2.1 Production reconciliation note

The currently deployed Ubuntu runtime remains `LEGACY_RUNTIME_UNVERIFIED_REVISION` under Final Design v6.1.

Read-only reconciliation performed before this revision established that most current backend core, discovery, frontend, and watchdog source files match canonical GitHub `main` exactly, while the deployed runtime retains localized legacy drift around Ollama/AI configuration, `config.py`, `main.py`, Compose/runtime versions, and lacks the Wave 0–1C migration/metadata foundations.

This does **not** make the deployed runtime a Git source-of-truth and does not permit retrospective assignment of a Git SHA. Wave 1D is designed against the canonical Wave 1C Git head, not against mutable files under `/srv/waterfallhunter`.

No Production file was changed during this reconciliation.

## 3. Non-goals

Wave 1D does **not**:

- train, fit, calibrate, or promote a true probability model;
- invent a new probability proxy;
- recalibrate, optimize, or scientifically promote Final Signal Score weighting;
- redistribute the invalid probability weight into other ranking components;
- introduce a replacement predictive component merely to keep a 100-point legacy ranking total;
- change ScoreV2 component weights or threshold policy;
- turn Evidence Quality/freshness into directional predictive evidence;
- change lifecycle semantics to Lifecycle V2;
- add portfolio simulation, leverage policy, or live execution;
- add Product Layer UI architecture;
- reintroduce or remove legacy Production-only AI/Ollama behavior as part of this wave;
- perform Production backup, migration, legacy classification, deployment, restart, Telegram send, or live trading;
- merge any PR without explicit `MERGE_APPROVAL`;
- introduce a new freshness threshold without evidence and separate review.

`calibrated_probability` remains nullable and must remain `None` until a later scientific promotion wave produces valid strict OOS calibration evidence.

## 4. Sequencing

Implementation is serialized even though Final Design shows P1-D/P1-E/P1-F as sibling workstreams:

```text
Wave 1C certified development state
  -> P1-D Probability Cleanup
  -> P1-E Freshness Contracts
  -> P1-F Strict Outcome / Calibration Filtering
  -> Wave 1D final regression and independent review
  -> W1-D = MERGE_READY_PENDING_MERGE_APPROVAL
  -> P2 Typed API
```

This serialization is an execution/TDD strategy, not an architecture dependency claim.

Reason: all three touch shared decision/report semantics. Serial TDD keeps regression attribution deterministic and avoids conflicting changes to contracts, ranking, and consumers.

## 5. Global invariants

The following invariants apply to all P1-D/P1-E/P1-F changes:

- `LIVE_TRADING_ENABLED=false`.
- Paper/observational only.
- LBank remains the user-facing execution source of truth.
- ISOLATED margin remains mandatory; Cross remains forbidden.
- Wave 1C `signal_metadata` remains authoritative for signal class/profile/score lineage.
- Missing lineage never defaults to STRICT.
- Unresolved/conflicting legacy rows remain outside canonical production cohorts.
- No consumer may reconstruct historical signal class from current defaults.
- No probability-like label may be attached to ScoreV2, watch score, FinalRanking score, Final Signal Score, or the current unconditional hit-rate.
- Evidence Quality/freshness may gate or qualify usability, but is not itself directional evidence.
- Existing non-probability FinalRanking weights are legacy/unvalidated observational behavior until later scientific calibration; preserving them during a minimal-change transition does not promote or validate them.
- No new model-semantic difference may be normalized into Golden fixtures without explicit review.
- Every semantic change must have RED evidence before the minimal GREEN implementation.

## 6. P1-D — Probability Cleanup

### 6.1 Current problem

`PositionCalculator._tp_probability()` computes whether a generic historical 5m candle sees a future low at the TP2 ratio within 24h. It is not conditioned on the current setup, ScoreV2, lifecycle, microstructure, derivatives, anti-chase state, or TP-before-SL ordering. Windows overlap heavily.

The current runtime then:

- stores the value as `tp_24h_probability`;
- rejects a position setup when the metric cannot be computed;
- feeds the metric into `FinalRanking` as `empirical_probability` with 10 points;
- treats availability of that invalid component as part of ranking evidence confidence;
- exposes it through user-facing notification/dashboard semantics.

This is statistically misleading and creates invalid eligibility, ranking, and evidence-completeness coupling.

### 6.2 Target semantics

The runtime decision path must not require, score, display, or use availability of this metric as a confidence penalty.

Required behavior:

- absence of completed historical candle samples must **not** reject an otherwise valid execution setup;
- `FinalRanking` must have no probability component derived from this metric;
- absence of the removed metric must not reduce ranking confidence/evidence completeness;
- no canonical decision packet, dashboard-facing payload, or Telegram-facing payload may label the metric as probability/confidence/success chance;
- `calibrated_probability` remains `None`;
- Final Signal Score remains explicitly non-probabilistic.

### 6.3 Research-only handling

Preferred implementation: remove the metric from the runtime decision packet entirely.

If retained for research compatibility, it must be isolated from the decision/ranking path and renamed exactly or equivalently to:

`unconditional_24h_downside_hit_rate`

Any retained packet must state `research_only=true` and must not be consumed by production-facing ranking/report/notification code.

No migration of historical JSON is required solely to rename the old field. Historical payloads remain historical evidence and must not be silently rewritten.

### 6.4 FinalRanking transitional policy after cleanup

The current invalid probability component and its availability/confidence penalty are removed.

Wave 1D must **not** convert that removal into an implicit recalibration of FinalRanking or Final Signal Score.

For a minimal-change implementation, the remaining observational components may preserve their pre-existing numeric weights as a transitional implementation detail:

- cascade readiness
- signal score
- execution quality
- relative weakness
- freshness

If those legacy numeric weights are retained, that retention means only **“unchanged because this wave is not authorized to recalibrate them.”** It does not mean the remaining weights, their sum, or their normalization are scientifically validated, optimal, calibrated, or promoted as the target Final Signal Score contract.

Rules:

- no removed probability weight is redistributed;
- no replacement component is invented;
- no phantom missing-weight penalty remains;
- no new 100-point total is manufactured for cosmetic continuity;
- no freshness/evidence-quality value is newly promoted into directional evidence;
- any necessary arithmetic normalization change must be the smallest deterministic change required to remove the invalid component and must be documented as transitional observational behavior;
- any proposal to re-estimate, optimize, calibrate, or promote Final Signal Score weights belongs to later strict OOS scientific work and requires its own evidence/review.

A version bump is required for the ranking packet because its component contract changes.

The resulting ranking must remain explicitly:

- observational;
- uncalibrated as a success probability;
- non-authoritative for trade eligibility;
- not a claim that its surviving legacy weights are scientifically validated.

Expected semantic diff is restricted to:

- removal of the probability component;
- removal of probability-availability confidence penalty;
- mechanically resulting observational ranking score/confidence/order changes;
- removal of probability-dependent rejection in PositionCalculator;
- contract/version/labels required to make the transitional status explicit.

Any unrelated ScoreV2, lifecycle, signal-class, eligibility, Entry/TP/SL, leverage, or execution-policy diff is a blocker.

## 7. P1-E — Freshness Contracts

### 7.1 Independent freshness axes

Analysis freshness and reference-price freshness are independent facts.

Canonical fields already exist in the Wave 1A/Wave 1C domain model:

- `analysis_observed_at`
- `analysis_age_seconds`
- `reference_observed_at`
- `reference_age_seconds`

They must not substitute for one another.

### 7.2 Reproducible age semantics

Age values are derived from the corresponding canonical observation timestamp at an explicit evaluation time.

For a packet evaluated at `evaluated_at`:

```text
analysis_age_seconds = evaluated_at - analysis_observed_at
reference_age_seconds = evaluated_at - reference_observed_at
```

Rules:

- negative age is invalid;
- missing analysis timestamp means analysis freshness is UNAVAILABLE;
- missing reference timestamp means reference freshness is UNAVAILABLE;
- a fresh reference timestamp cannot make stale analysis appear live;
- a fresh analysis timestamp cannot make stale execution/reference levels authoritative;
- if a packet persists both timestamp and age, inconsistency beyond deterministic rounding tolerance is invalid/fail-closed.

No new numeric freshness threshold is defined by this design. Implementation must use an already-approved/current policy where one exists. Any new threshold requires separate evidence and review.

### 7.3 Status semantics

At minimum, each axis must support explicit status semantics equivalent to:

- `LIVE`
- `STALE`
- `UNAVAILABLE`

The exact enum/type location may follow existing project conventions, but consumers must not infer the status from one combined `age_seconds` field.

### 7.4 Decision consequences

Freshness is an eligibility/data-quality axis, not a predictive score proxy.

Required consequences:

- stale/unavailable **analysis** cannot produce an execution-eligible strict confirmation;
- stale analysis adds `STALE_ANALYSIS` or equivalent canonical qualifier/reason code;
- stale/unavailable **reference** prevents authoritative execution levels at that observation boundary;
- stale reference adds `STALE_REFERENCE` and, where levels cannot be trusted, `EXECUTION_LEVELS_UNAVAILABLE`;
- signal identity and persisted signal class are not rewritten because reference data later goes stale;
- freshness changes must not silently alter historical signal metadata lineage;
- this wave does not assign a newly invented directional weight to freshness.

### 7.5 Four-state acceptance matrix

The implementation must have explicit tests for:

| Analysis | Reference | Required interpretation |
| --- | --- | --- |
| LIVE | LIVE | normal observational eligibility evaluation |
| STALE | LIVE | analysis remains stale; fresh price cannot mask it |
| LIVE | STALE | analysis may be current, but execution/reference levels are unavailable/degraded |
| STALE | STALE | fail-closed for strict execution eligibility |

UNAVAILABLE variants require equivalent fail-closed tests.

## 8. P1-F — Strict Outcome / Calibration Filtering

### 8.1 Scope

Wave 1C established authoritative `signal_metadata`, canonical INNER-JOIN consumers, and STRICT-default execution outcome reporting. P1-F extends that guarantee to every production-facing outcome/calibration input and research export that could later be used for promotion.

### 8.2 Default production cohort

Production-facing outcome/calibration/reporting entry points default to:

`signal_class_scope = ["STRICT"]`

Rules:

- STRICT is explicit, not inferred;
- missing signal class/profile/score lineage fails closed;
- EXPERIMENTAL is excluded from production aggregates by default;
- MIXED data is never presented as a production/natural strict dataset;
- EXPERIMENTAL or MIXED modes require explicit caller opt-in and must declare `research_only=true`;
- research-only cohorts must declare `promotion_allowed=false`.

### 8.3 Calibration dataset manifest

Any dataset/report intended to feed later calibration must carry a deterministic manifest with at least:

- manifest/contract version;
- generated/evaluated timestamp;
- signal class scope;
- strategy profile scope;
- score version scope;
- model generation scope;
- source revision/provenance identity;
- observation window start/end;
- included sample count;
- excluded sample count;
- deterministic exclusion reason counts;
- outcome horizon definition;
- outcome price-source semantics;
- deterministic `dataset_identity_hash` over canonical semantic cohort/filter/provenance/input identity, excluding volatile `generated_at`;
- `research_only` flag;
- `promotion_allowed` flag.

If lineage is heterogeneous, the manifest must enumerate it explicitly or fail closed; it must not collapse distinct profiles/versions into one implied cohort.

### 8.4 Current calibration tooling

Existing historical calibration/backtest tooling may continue as research tooling, but it cannot be treated as strict promotion evidence unless the input is cohort-pure and the manifest requirements above are satisfied.

No current historical report is upgraded by declaration alone.

P1-F does not produce `P(TP2 before SL | setup, score_bucket, regime, execution_quality, anti_chase_bucket)`.

That probability belongs to Wave 5 after strict dataset collection and walk-forward/holdout/OOS calibration with sample size, uncertainty, calibration curves, and Brier score.

P1-F also does not promote new Final Signal Score weights. It creates the cohort/provenance conditions required for later scientific evaluation of such weights.

## 9. Contract/versioning policy

Semantic changes require versioned output contracts.

At minimum:

- FinalRanking packet version changes when the probability component is removed;
- the new version must preserve the distinction between transitional observational ranking and a scientifically promoted Final Signal Score;
- any new explicit freshness status contract is versioned;
- calibration dataset manifest is versioned independently from ScoreV2.

Historical persisted packets are not rewritten to pretend they were produced under the new semantic contract.

Backward compatibility is read-only where needed; new runtime producers must emit only the new contract after cutover.

## 10. Persistence and migration impact

No new Production schema migration is planned for Wave 1D.

Rationale:

- Wave 1C already persists first-class signal class/profile/score lineage and analysis/reference observation timestamps;
- freshness ages are derivable observations, not immutable stored identity;
- calibration manifests can be generated as explicit research/report artifacts.

If implementation discovers that a new persisted Production column/table is necessary, work stops and returns to design review. No migration may be introduced silently under this design.

The existing Wave 1C Production migration/classification remains separately gated by `MIGRATION_APPROVAL`; Wave 1D design approval does not authorize it.

## 11. Error handling / fail-closed rules

- invalid/missing canonical lineage: exclude from strict calibration;
- invalid timestamp/age relationship: fail packet validation or mark freshness unavailable; never assume LIVE;
- missing probability proxy: no error in the runtime decision path;
- missing probability proxy: no ranking evidence-confidence penalty;
- missing true calibrated probability: valid state is `None`, not fallback to score/hit-rate;
- malformed/heterogeneous calibration manifest: promotion not allowed;
- research-only cohort accidentally requested through production default: reject or force explicit research mode.

## 12. TDD and regression strategy

Each workstream follows RED -> minimal GREEN -> full regression -> independent review.

### P1-D focused RED tests

Prove current failures before implementation:

- PositionCalculator rejects when the old hit-rate is unavailable;
- FinalRanking includes `empirical_probability`;
- missing `empirical_probability` reduces current ranking confidence;
- user-facing formatter/notifier exposes `tp_24h_probability` where still present;
- canonical decision semantics can be confused with probability-like labels.

### P1-D GREEN gates

- no runtime rejection caused solely by missing hit-rate samples;
- no probability component in FinalRanking;
- no confidence/evidence-completeness penalty caused by absence of the removed metric;
- no runtime consumer reference to `tp_24h_probability` for decision/ranking/dashboard/Telegram semantics;
- true `calibrated_probability` remains `None`;
- resulting FinalRanking is explicitly versioned/observational/transitional, not presented as calibrated probability or scientifically promoted Final Signal Score;
- expected ranking delta is fully attributable to the approved cleanup and minimal deterministic arithmetic consequences;
- surviving legacy weights are not described as calibrated, optimal, or promoted.

### P1-E focused RED tests

- fresh reference + stale analysis cannot report analysis LIVE;
- stale reference cannot remain authoritative for execution levels;
- missing timestamp cannot become age 0/fresh;
- negative/inconsistent ages are rejected;
- four-state matrix fails under current combined/implicit behavior where applicable.

### P1-E GREEN gates

- independent status and age semantics pass all matrix tests;
- reason/qualifier behavior is deterministic;
- no signal-class/lineage mutation occurs from freshness evaluation;
- no newly invented directional freshness weight is introduced.

### P1-F focused RED tests

- experimental/mixed input reaches any calibration/report path that is supposed to be production-default strict;
- missing lineage can be accepted without explicit exclusion;
- calibration report lacks deterministic cohort/provenance manifest.

### P1-F GREEN gates

- production defaults are STRICT-only everywhere in scope;
- EXPERIMENTAL/MIXED require explicit research mode;
- research mode is non-promotable;
- manifest identity/exclusion counts are deterministic;
- no unresolved/conflicting legacy signal enters a strict dataset;
- no score/probability model is promoted merely because a clean manifest exists.

## 13. Golden/model regression policy

Wave 1D contains intentional semantic cleanup around the invalid probability proxy and independent freshness semantics.

Therefore Golden review is differential, not a blind equality assertion.

Allowed differences must be enumerated before fixture update and limited to approved P1-D/P1-E semantics.

For P1-D, allowed ranking differences are only those mechanically caused by:

- removing the invalid probability component;
- removing its availability/confidence penalty;
- the smallest deterministic normalization/arithmetic adjustment needed after removal;
- the required ranking contract/version/label change.

Those allowed differences must **not** be interpreted as evidence that the surviving ranking weights are calibrated or scientifically optimal.

All of the following remain blockers if they change unexpectedly:

- ScoreV2 component computation;
- signal class / strategy profile;
- lifecycle state;
- eligibility gates unrelated to the old hit-rate or approved freshness correction;
- reason codes unrelated to probability/freshness correction;
- Entry/TP1/TP2/SL arithmetic;
- LBank contract identity;
- ISOLATED margin semantics;
- leverage policy;
- execution suitability/cost math;
- deterministic replay ordering outside the approved ranking delta.

Golden fixtures must never be normalized merely to make CI green.

## 14. Static/security/review gates

For every implementation slice:

- backend full regression;
- runtime parity;
- frontend typecheck/build;
- dependency audit;
- repository hygiene;
- exact production artifact-family container validation and revision labels;
- Sonar Quality Gate / security-hotspot review;
- CodeRabbit independent review;
- controller semantic review;
- all valid functional/integrity/security findings fixed with regression tests.

Runtime parity here refers to the canonical future artifact family; the current deployed legacy runtime remains `LEGACY_RUNTIME_UNVERIFIED_REVISION` and is not retrospectively treated as a verified Git artifact.

## 15. Planned PR topology

Design PR:

```text
base: feat/wave1c2-persistence-legacy-classification-v1
head: feat/wave1d-probability-freshness-strict-filtering-design-v1
```

After design approval and an implementation plan, implementation is expected to use serial stacked slices:

```text
P1-D probability cleanup
  -> P1-E freshness contracts
  -> P1-F strict calibration filtering
  -> final Wave 1D certification/evidence
```

Exact implementation branch names and file lists belong in the implementation plan, not this design.

## 16. Production and approval gates

Design approval permits development-side implementation preparation only.

It does not grant:

- `MERGE_APPROVAL`;
- `BACKUP_EXECUTION_APPROVAL`;
- `MIGRATION_APPROVAL`;
- `DEPLOYMENT_APPROVAL`;
- Production DB writes/classification;
- Production Docker/service changes;
- Production source/config changes;
- Telegram test sends;
- live trading.

Wave 1D implementation should remain development-side until its own final certification reaches `MERGE_READY_PENDING_MERGE_APPROVAL`.

The planned first mutating host-touch point remains after the required development merges/certification and a fresh Production read-only preflight. At that point the controller must explicitly provide the user with exact host commands and stop at each independent approval gate.

The current legacy Ollama/config/Compose drift is recorded as runtime evidence. It is not automatically preserved or reintroduced into canonical source by Wave 1D, and no Production behavior is changed by this design document.

## 17. Acceptance criteria

Wave 1D may be certified development-side only if all are true:

1. no decision/ranking/dashboard/Telegram semantic consumer uses `tp_24h_probability` as probability/confidence;
2. missing old hit-rate data cannot reject an otherwise valid position setup;
3. absence of the removed hit-rate cannot reduce FinalRanking evidence confidence/completeness;
4. `calibrated_probability` has no proxy fallback and remains nullable;
5. Final Signal Score is explicitly non-probabilistic;
6. FinalRanking after cleanup is explicitly versioned, observational, transitional, and not represented as scientifically calibrated/promoted;
7. no probability weight was redistributed or replaced merely to preserve a legacy total;
8. surviving legacy ranking weights are not claimed to be calibrated/optimal/promoted;
9. analysis and reference freshness are independent and pass the LIVE/STALE/UNAVAILABLE matrix;
10. stale analysis cannot be masked by fresh reference price;
11. stale reference cannot remain authoritative for execution levels;
12. freshness is not newly assigned directional predictive weight;
13. production outcome/calibration/report defaults are STRICT-only;
14. EXPERIMENTAL/MIXED modes are explicit, research-only, and non-promotable;
15. missing/unknown lineage never defaults to STRICT;
16. calibration inputs carry deterministic cohort/provenance manifests;
17. no Production schema migration was introduced without design re-approval;
18. all expected semantic diffs are explicitly enumerated and all unexpected Golden/model diffs are blockers;
19. full CI, artifact, static/security, and independent review gates pass;
20. current Production remains `LEGACY_RUNTIME_UNVERIFIED_REVISION` until a separately approved verified deployment replaces it;
21. no Production mutation, deployment, Telegram send, live trade, or merge occurred without its separate approval.

Only after these criteria pass may the controller state become:

`W1-D = MERGE_READY_PENDING_MERGE_APPROVAL`
