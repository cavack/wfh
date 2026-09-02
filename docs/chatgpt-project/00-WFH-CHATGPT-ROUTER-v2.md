# WaterfallHunter — ChatGPT Project Router v2

GitHub `cavack/wfh` is the canonical source. This Drive/Project Sources bundle is routing and installation metadata only; it intentionally does not duplicate canonical skill bodies.

## Mandatory workflow

1. Resolve the current target branch and SHA in GitHub before trusting older findings.
2. Read this router and `01-WFH-SKILL-CATALOG-v2.md`.
3. Select the smallest relevant Council route and canonical skill set.
4. Fetch every selected `skills/waterfallhunter/<skill>/SKILL.md` completely from the current target SHA before analysis or mutation.
5. Classify material findings as `VERIFIED_FACT`, `REPRODUCED_DEFECT`, `INFERENCE`, `DEBT`, or `PROPOSAL`.
6. Treat tool/plugin/MCP presence and authorization as separate facts. Missing optional capability is `UNAVAILABLE`, never guessed evidence.
7. Preserve protected model, lifecycle, anti-chase, provenance, persistence-before-notification, scientific-validation, and execution-policy invariants unless separately authorized through their owning skills.
8. Route code completion through `verification-regression` and production states only through `release-production-certification`.

## Council v2 routes

- skill-system audit: `engineering-orchestrator → skill-system-curator → verification-regression`
- runtime incident: `engineering-orchestrator → observability-incident-response → runtime-reliability-performance → backend-data-architecture → verification-regression → release-production-certification`
- strategy/model: `engineering-orchestrator → market-data-evidence-quality → strategy-score-lifecycle → scientific-backtest-validation → verification-regression → release-production-certification`
- frontend contract: `engineering-orchestrator → api-contract-schema-guardian → frontend-dashboard-ux → verification-regression`
- security/dependency: `engineering-orchestrator → security-supply-chain → verification-regression → release-production-certification`

## Safety

`LIVE_TRADING_ENABLED=false` remains mandatory. Missing market data is unavailable evidence, not directional evidence. Only canonical backend decision logic may determine ranking/eligibility. CI success alone is not production verification.
