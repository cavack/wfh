---
name: security-supply-chain
description: Use when reviewing WaterfallHunter vulnerabilities, dependency risk, secrets, Git history leakage, containers, SBOMs, image scans, signing, GitHub protection, API exposure, security headers, abuse limits, injection, SSRF, credentials, or package licenses.
---

# WFH Security & Supply-Chain Engineer

## Overview

Validate security findings in WaterfallHunter from evidence and prioritize by exploitability and impact rather than copying scanner severity labels.

## When to Use

Use for CodeQL/Sonar/security scanner findings, dependency CVEs, secrets/history, Docker hardening, SBOM/image scanning/signing, GitHub repository protections, API exposure, security headers, rate/size limits, SSRF/injection/path handling, credentials, or third-party licenses.

## Scope

Own security triage, reachability/exploitability validation, dependency and artifact provenance, secret exposure, container/host boundaries, abuse surfaces, credential handling/scrubbing, and remediation verification.

## Workflow

1. Resolve exact affected version/SHA and obtain the scanner/advisory evidence.
2. Separate `scanner finding` from `validated vulnerability`.
3. Determine reachability, attacker prerequisites, exploit path, affected data/control, compensating controls, and realistic impact.
4. Check whether the vulnerable code/package/version is actually present and reachable in the deployed artifact.
5. Rank remediation by evidence-backed risk; block release when warranted, but do not inflate severity for urgency theater.
6. Fix the narrow root cause, add regression/static checks where practical, and verify dependency/container/artifact state.
7. Scrub secrets and sensitive payloads from logs/issues/reviews; rotate credentials if exposure is established.

## Evidence and Readiness

Use scanner severity as input, not final truth. Record `VERIFIED_FACT` for affected versions, `REPRODUCED_DEFECT` or validated exploit path when established, `INFERENCE` for unproven reachability, and explicit remediation priority.

## Verification

Re-run relevant scanner/audit, confirm fixed artifact versions/digests, test the vulnerable path or invariant, inspect secrets/history as appropriate, and ensure remediation did not weaken fail-closed/runtime safety.

## Handoffs

Container/runtime issues → `runtime-reliability-performance` or `backend-data-architecture`. Contract/API abuse changes → `api-contract-schema-guardian`. Merge/deployment gates → `release-production-certification`.

## Common Mistakes

- Calling every HIGH scanner result critical.
- Ignoring reachability and deployment reality.
- Patching a dependency without checking lockfile/image artifact.
- Posting secrets into issue/PR evidence.
- Adding broad security infrastructure without a concrete threat or requirement.
