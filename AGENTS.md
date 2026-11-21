# JSI Build & Functional Verification Harness

This repository (`jsi-build-verify`) provides a self-contained reusable GitHub Actions workflow, verification scripts, and Pi Coding Agent skill (`jeffs-automated-build-deploy-agent`) used as an automated build, run, and functional test harness for target repositories.

## Core Execution Rules
- **Verify, Don't Guess**: Inspect actual project manifests (`pom.xml`, `build.gradle`, `pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile`, etc.) before running builds or tests.
- **Target Repo Config**: If the target repository contains a `.jsi-verify.yml` (or configured `config_file`), follow its build, start, and functional verification instructions.
- **Structured Verdict Required (CI Mode)**: Always write `/tmp/jsi-verify/verdict.json` with `status` (`"pass"`, `"fail"`, or `"blocked"`), `summary`, `checks`, and `failure_reason` (empty on pass) before exiting.
- **Verification-Gated Docs**: Only create or update `docs/BUILD_VERIFICATION.md` and `README.md` when verification genuinely passes. Never run `git commit` or `git push` inside GitHub Actions — the workflow handles git publishing.
- **Secret & Git Hygiene**: Never commit `.env`, private keys (`*.key`, `*.pem`, `*.p12`), local registry configs, or temporary verification files. Clean up background servers and temporary files before exiting.
- **Secret-Scanner-Safe Verification Docs**: Summarize crypto/API verification results in plain prose (avoiding `key: "high-entropy"` JSON fragments that trigger Gitleaks false positives); `scripts/check_doc_hygiene.py` runs in the `Check for Gitleaks FPs` step before publishing docs.
- **Release Tagging for Dependabot**: Every commit pushed to `main` in this repository must be tagged with a new semantic version (`vX.Y.Z`) and published as a GitHub Release so Dependabot opens update PRs in consumer repositories.
- **Public Repo Cleanliness**: Do not add local-only helper scripts (such as `skills-backup` sync scripts) to this public action repository.
- **Fork Guardrail**: Never apply unilateral updates to forked repositories unless upstream is verified abandoned; in GitHub Actions CI, fork execution is blocked by the workflow.

## Repository Layout
- `.github/workflows/jsi-build-verify.yml` — Reusable `workflow_call` / `workflow_dispatch` test harness workflow.
- `.github/workflows/test.yml` — Self-test CI workflow for this repository.
- `scripts/summarize_pi_usage.py` — Parses Pi `--mode json` JSONL logs into token/cost reports.
- `scripts/evaluate_verdict.py` — Evaluates `/tmp/jsi-verify/verdict.json` and enforces pass/fail gating.
- `skills/jeffs-automated-build-deploy-agent/` — Verification skill and stdlib helper scripts (`api_verify.py`, `browser_verify.py`, `discover_top_repos.py`).
- `rules/` — Operational guardrails appended to the agent system prompt.
- `tests/` — `pytest` suite validating all harness scripts and workflow integrity.
