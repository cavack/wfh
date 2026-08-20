# Advisory CI integrations

This directory contains GitHub Actions workflows used by WaterfallHunter.

The `CodeQL` and `Coverage` workflows are intentionally advisory during their initial rollout. They are not part of the protected `main` branch required-status-check set. Existing required checks remain authoritative until these integrations have demonstrated stable signal quality across multiple pull requests.

- `codeql.yml` scans Python and JavaScript/TypeScript with GitHub CodeQL.
- `coverage.yml` runs the backend test suite with coverage and uploads the report to Codecov.
- SonarQubeCloud and Aikido Security are GitHub App integrations and do not require duplicate repository workflows here.

Promotion of any advisory check to a required merge gate is a separate governance decision.
