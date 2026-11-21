# JSI Automated Build & Functional Verification (`jsi-build-verify.yml`)

A reusable GitHub Actions workflow that runs the **`jeffs-automated-build-deploy-agent`** skill via the headless **Pi Coding Agent** (`@earendil-works/pi-coding-agent`) on GitHub-hosted runners for any repository.

---

## What It Was Designed to Do

Traditional CI pipelines require custom per-repository build, start, and smoke-test scripts. `jsi-build-verify.yml` provides a single, drop-in reusable workflow that can verify **any** repository end-to-end:

- **Adaptive Build & Stack Detection**: Inspects actual project manifests (`pom.xml`, `build.gradle`, `pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile`, OPA/K8s bundles) rather than relying on GitHub language metadata.
- **Trusted OSS Registry Support (`jsigroup-oss`)**: Automatically authenticates to your split-horizon Trusted OSS Harbor/Gatekeeper registry (`https://jsigroup-oss.duckdns.org`) via mTLS for any repository already onboarded with `trusted-oss-github-setup`, while transparently falling back to public upstream registries when unset.
- **Real Functional Verification**: Goes beyond unit tests by starting the application on isolated ports and verifying live behavior with:
  - Guided headless Chrome (CDP) checks (`browser_verify.py`) — DOM assertions, multi-step UI clicks, console/JS exception checks, and screenshots.
  - `curl` API probes (`api_verify.py`) — HTTP status assertions, JSON/binary validation, and endpoint latency.
- **Verification-Gated Documentation**: Updates `docs/BUILD_VERIFICATION.md` and `README.md` **only** if the build and functional checks genuinely pass, enforcing strict git hygiene so credentials or temporary files are never committed.
- **Transparent Token & Cost Accounting**: Tracks and reports exact LLM token consumption and estimated USD cost on every run (whether verification passes or fails).
- **Safe by Default**: Blocks execution on forked repositories and bot commits, fails fast with clear setup instructions when required secrets are missing, and defaults to opening a Pull Request (`commit_mode: pr`) rather than pushing directly to the default branch.

---

## How It Accomplishes That

### Execution Pipeline

1. **Fork & Loop Guardrail**: The `verify` job runs only when `!github.event.repository.fork` and `github.actor != 'github-actions[bot]'`.
2. **Provider, Model & Fail-Fast Secret Gate**:
   - Resolves provider in order: `inputs.provider` → `vars.PI_PROVIDER` → **`google`** (Gemini; `gemini` is normalized to `google`).
   - Resolves model in order: `inputs.model` → `vars.PI_MODEL` → provider default (**`gemini-3.1-pro-preview`** for `google`).
   - Verifies that the matching API key secret (`GEMINI_API_KEY` by default, or the selected provider's secret / generic `PI_API_KEY`) is populated. If missing, the job **immediately fails** with an `::error::` annotation and a Step Summary explaining how to configure the secret before any runner time is spent installing tools.
3. **Target & Self-Contained Tooling Checkout**:
   - Checks out the calling repository (`fetch-depth: 0`) and this self-contained repository (`AGENTS.md`, `rules/`, `skills/jeffs-automated-build-deploy-agent/`, and `scripts/summarize_pi_usage.py`) into `.jsi-verify-tools/` (added to `.git/info/exclude` so it never pollutes `git status`). No external skill repository is required.
4. **Trusted OSS mTLS Bootstrap (Conditional)**:
   - When `use_trusted_oss: true` and `vars.TRUSTED_OSS_CACHE_URL` is defined, writes `OSS_MTLS_CLIENT_CERT` and `OSS_MTLS_CLIENT_KEY` to `~/.oss-tls/`, validates `/healthz` and the Trusted OSS GPG public key (`TRUSTED_OSS_GPG_EMAIL`), builds a PKCS#12 keystore for Maven/Gradle (`MAVEN_OPTS`, `GRADLE_OPTS`, `~/.m2/settings.xml`), and exports a combined PEM (`PIP_CLIENT_CERT`, `PIP_INDEX_URL`, `UV_INDEX_URL`, `UV_NATIVE_TLS=true`) for Python builds.
5. **Isolated Headless Pi Execution**:
   - Installs `@earendil-works/pi-coding-agent` on Node.js 22, appends `.jsi-verify-tools/AGENTS.md` and `.jsi-verify-tools/rules/*.md` via `--append-system-prompt`, and runs:
     ```bash
     pi --mode json --no-session --no-extensions --no-mcp --no-approve \
        --no-skills --skill .jsi-verify-tools/skills/jeffs-automated-build-deploy-agent \
        --append-system-prompt .jsi-verify-tools/AGENTS.md \
        --append-system-prompt .jsi-verify-tools/rules/*.md \
        --provider "$PI_PROVIDER" --model "$PI_MODEL" --thinking "$PI_THINKING" ...
     ```
   - Pi executes Steps 3–6 of `jeffs-automated-build-deploy-agent` in single-repository CI mode (skipping repo discovery, git clone/pull, and LAN-only `.local` URLs) and streams structured JSONL events to `/tmp/jsi-verify/pi-events.jsonl`.
   - Pi is explicitly instructed **not** to run `git commit` or `git push`.
6. **Structured Verdict & Pass/Fail Gating (`if: always()`)**:
   - The agent writes `/tmp/jsi-verify/verdict.json` (`status: pass | fail | blocked`, `summary`, `checks`, `failure_reason`).
   - Runs `scripts/evaluate_verdict.py` to normalize the verdict, publish a Markdown verdict table to `$GITHUB_STEP_SUMMARY`, and expose `verification_status` and `verification_summary` as workflow outputs.
   - When `fail_on_error: true` *(default)*, the final step fails the job if `verification_status != 'pass'`, preventing false-green CI checks when the agent exits cleanly after reporting a build/test failure.
7. **Token Consumption & Cost Report (`if: always()`)**:
   - Runs `scripts/summarize_pi_usage.py` over `pi-events.jsonl` to aggregate every assistant turn and compaction event.
   - Publishes a Markdown table (Input, Output, Cache Read, Cache Write, Total Tokens, Estimated USD Cost, Assistant Turns, and Tool Call Breakdown) to `$GITHUB_STEP_SUMMARY`, job logs, reusable workflow outputs, and `/tmp/jsi-verify/token-usage.{json,md}`.
8. **Hygiene-Checked Documentation Publishing & Optional PR Commenting**:
   - Runs only if `verification_status == 'pass'` and `commit_mode != report-only`.
   - Stages **exclusively** `docs/BUILD_VERIFICATION.md` and `README.md`.
   - Depending on `commit_mode`:
     - `pr` *(default)*: Force-updates branch `docs/jsi-build-verify` and opens/updates a PR containing the verdict and token usage report in the PR body.
     - `direct`: Commits with `[skip ci]` and pushes directly to the current branch.
     - `report-only`: Skips git commits/PRs and uploads outputs as artifacts only.
   - When `comment_on_pr: true` on `pull_request` events, posts or updates a sticky PR comment with the verdict and token usage summary.
9. **Artifact Upload (`if: always()`)**:
   - Uploads `verdict.json`, `verdict-normalized.json`, `verdict.md`, `token-usage.json`, `token-usage.md`, `pi-events.jsonl`, any headless Chrome screenshots (`/tmp/jsi-verify/*.png`), and `docs/BUILD_VERIFICATION.md` (30-day retention).

---

### Quick Start (Caller Workflow)

Add `.github/workflows/verify.yml` to any target repository:

```yaml
name: JSI Build & Verify
on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1"

permissions:
  contents: write
  pull-requests: write

jobs:
  verify:
    uses: jsoehner/jsi-build-verify/.github/workflows/jsi-build-verify.yml@main
    with:
      # Optional: override provider/model (defaults: google / gemini-3.1-pro-preview)
      # provider: anthropic
      # model: claude-sonnet-4-5
      commit_mode: pr
    secrets:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      # Optional: include if using Trusted OSS (jsigroup-oss) mTLS
      OSS_MTLS_CLIENT_CERT: ${{ secrets.OSS_MTLS_CLIENT_CERT }}
      OSS_MTLS_CLIENT_KEY: ${{ secrets.OSS_MTLS_CLIENT_KEY }}
```

### PR Test-Harness Mode (Gating Check + Sticky PR Comment)

```yaml
name: Functional Verification
on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  verify:
    uses: jsoehner/jsi-build-verify/.github/workflows/jsi-build-verify.yml@v1.0.0
    with:
      workflow_ref: v1.0.0
      commit_mode: report-only
      fail_on_error: true
      comment_on_pr: true
    secrets:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      # Optional: include if using Trusted OSS (jsigroup-oss) mTLS
      OSS_MTLS_CLIENT_CERT: ${{ secrets.OSS_MTLS_CLIENT_CERT }}
      OSS_MTLS_CLIENT_KEY: ${{ secrets.OSS_MTLS_CLIENT_KEY }}
```

> [!TIP]
> **SHA-Pinning for Supply-Chain Integrity:** When pinning to an immutable 40-character commit SHA (e.g., `uses: jsoehner/jsi-build-verify/.github/workflows/jsi-build-verify.yml@<SHA>`), also pass `workflow_ref: <SHA>` under `with:` so the bundled tooling checkout (`.jsi-verify-tools/`) is pinned to the exact same commit rather than floating on `main`.

### End-to-End Onboarding Checklist

1. **Visibility:** Ensure `jsoehner/jsi-build-verify` is **public** (personal private repos cannot share reusable workflows).
2. **Secret:** Add `GEMINI_API_KEY` (or your chosen provider's secret + `PI_PROVIDER`/`PI_MODEL` repo variables) in the target repo's Actions secrets.
3. **Permissions:** Ensure the caller workflow grants `contents: write` and `pull-requests: write` (GitHub rejects callers with `contents: read` at startup because the reusable workflow declares `contents: write`).
4. **Draft PR Smoke Test:** Add `.github/workflows/verify.yml` in `commit_mode: report-only` with `comment_on_pr: true` on a branch and open a draft PR to verify zero-config detection, verdict gating, and token usage.
5. **Consolidate & Pin:** Retire any redundant legacy build/smoke workflows replaced by `verify.yml`, add an ADR if your repo enforces `adr-gatekeeper`, and pin `uses:` + `workflow_ref:` to a release tag or commit SHA before merging.

> [!IMPORTANT]
> Because the agent executes build/test commands with `--no-approve` and has access to configured LLM secrets, only run `pull_request` triggers on trusted repositories (forked PRs are automatically skipped by the workflow guardrail).

### Optional Per-Repo Config (`.jsi-verify.yml`)

Add an optional `.jsi-verify.yml` (or override via `config_file`) in any target repository to make verification faster and more deterministic:

```yaml
build: "npm ci && npm run build"
test: "npm test"
start: "PORT=13001 npm start"
checks:
  browser:
    - url: "http://127.0.0.1:13001/"
      expect: "Dashboard"
      click: ["#login-demo"]
  api:
    - "http://127.0.0.1:13001/health"
    - "http://127.0.0.1:13001/admin=403"
```

### Configuration Reference

#### Inputs (`with:`)
| Input | Default | Description |
| :--- | :--- | :--- |
| `provider` | `""` (`vars.PI_PROVIDER` → `google`) | Pi LLM provider (`google`, `anthropic`, `openai`, `openrouter`, `deepseek`, `mistral`, `groq`, `xai`). |
| `model` | `""` (`vars.PI_MODEL` → provider default) | Model ID (default for `google`: `gemini-3.1-pro-preview`). |
| `thinking` | `medium` | Pi reasoning level (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`). |
| `commit_mode` | `pr` | Verified doc handling: `pr`, `direct`, or `report-only`. |
| `fail_on_error` | `true` | Fail the workflow job when `verification_status != 'pass'`. |
| `config_file` | `.jsi-verify.yml` | Optional per-repo verification config file read from the target repo root if present. |
| `custom_instructions` | `""` | Optional extra instructions appended to the verification prompt. |
| `comment_on_pr` | `false` | Post/update a sticky PR comment with verdict and token usage on `pull_request` events. |
| `screenshot_mode` | `artifact` | Browser screenshot reporting: `artifact` (upload + link in report), `docs` (commit to `docs/verification-screenshots/`), or `branch` (inline images via orphan `jsi-verify-screenshots` branch). |
| `pi_version` | `1.6.0` | Pinned `@earendil-works/pi-coding-agent` npm version. |
| `use_trusted_oss` | `true` | Enable `jsigroup-oss` mTLS bootstrap when `vars.TRUSTED_OSS_CACHE_URL` is set. |
| `runner` | `ubuntu-latest` | GitHub Actions runner label (use `macos-latest` for Xcode/iOS/macOS repos). |
| `timeout_minutes` | `25` | Hard job timeout in minutes. |
| `workflow_repo` / `workflow_ref` | `jsoehner/jsi-build-verify` / `main` | Self-contained repository and ref providing the bundled skill, `AGENTS.md`, `rules/`, and `scripts/`. |

#### Secrets & Variables
| Name | Kind | Required | Purpose |
| :--- | :--- | :--- | :--- |
| `GEMINI_API_KEY` | Secret | **Yes (default)** | Required when `provider` is `google` (or `gemini`). |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `DEEPSEEK_API_KEY` / `MISTRAL_API_KEY` / `GROQ_API_KEY` / `XAI_API_KEY` | Secret | When selected | Required for the corresponding non-default provider. |
| `PI_API_KEY` | Secret | Optional | Generic fallback API key for any provider. |
| `OSS_MTLS_CLIENT_CERT` & `OSS_MTLS_CLIENT_KEY` | Secret | When Trusted OSS is set | mTLS client credentials for `jsigroup-oss`. |
| `PI_PROVIDER` / `PI_MODEL` | Variable | Optional | Repo/Org-level defaults for provider and model. |
| `TRUSTED_OSS_CACHE_URL` / `TRUSTED_OSS_MODE` / `TRUSTED_OSS_GPG_EMAIL` | Variable | Optional | Split-horizon Trusted OSS settings (from `trusted-oss-github-setup`). |

#### Outputs
`verification_status`, `verification_summary`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `total_tokens`, `estimated_cost_usd`.

---

## Troubleshooting

### 1. `Missing Required GitHub Secret (GEMINI_API_KEY)`
- **Cause**: The workflow defaults to `google` (Gemini) and intentionally halts before running Pi if `GEMINI_API_KEY` (or `PI_API_KEY`) is empty.
- **Fix**:
  1. Add `GEMINI_API_KEY` in **Repository (or Org) Settings → Secrets and variables → Actions → Secrets**.
  2. Verify the caller workflow includes `secrets: inherit` (or explicitly maps the secret).
  3. If using another provider (e.g., Anthropic), set `with.provider: anthropic` (or `vars.PI_PROVIDER`) and add `ANTHROPIC_API_KEY`.

### 2. `Trusted OSS Registry Unreachable` (`HTTP 000` / `403` / TLS failure)
- **Cause**: GitHub-hosted runner IP is blocked by pfSense, the mTLS client cert is expired/corrupted, or the external FQDN is proxied behind Cloudflare orange-cloud (which strips mTLS certs).
- **Fix**:
  1. Confirm `vars.TRUSTED_OSS_CACHE_URL` is `https://jsigroup-oss.duckdns.org` (never `http://oss.jsigroup.local:8080`).
  2. Verify pfSense `github_actions_cidrs` alias is up to date and DNS is DNS-only (not orange-cloud proxied).
  3. Re-sync secrets with `trusted-oss-github-setup` (`setup_trusted_oss_repo.py`) if the mTLS certificate was rotated.

### 3. `Trusted OSS GPG Mismatch`
- **Cause**: The key fetched from `${TRUSTED_OSS_CACHE_URL}/keys/trusted-oss-pubkey.asc` does not match `vars.TRUSTED_OSS_GPG_EMAIL` (default `oss-signing@the-techy.com`).
- **Fix**: Verify `vars.TRUSTED_OSS_GPG_EMAIL` matches the signing key identity currently served by Harbor/Gatekeeper.

### 4. Calling Repo Gets `workflow was not found` or `403` on `uses:`
- **Cause**: GitHub does not allow **personal** private repositories to share reusable workflows with other personal repositories (private reusable workflows only work across repos within a GitHub Organization).
- **Fix**: Ensure the host repository (`jsoehner/jsi-build-verify`) is **public** (with zero secrets committed) or host the workflow inside a GitHub Organization.

### 5. Build Fails with HTTP `451` from `jsigroup-oss`
- **Cause**: Harbor/Gatekeeper vulnerability gate rejected a dependency with a High/Critical CVE (or a transient scan race on a large JAR).
- **Fix**: Check the Pi job summary / `pi-events.jsonl` artifact. Genuine CVE `451` blocks are intentional security gates — upgrade the flagged dependency to the patched version reported by the agent rather than bypassing the registry.

### 6. `gh pr create` Fails with `GitHub Actions is not permitted to create or approve pull requests`
- **Cause**: Repository Actions settings restrict workflows from opening PRs.
- **Fix**: Enable **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve pull requests**, or switch to `commit_mode: report-only` (or `direct` on unprotected branches).

### 7. High Token Usage or Job Timeout
- **Cause**: Large monorepos, verbose test output, or heavy reasoning models can consume more tokens/time.
- **Fix**:
  - Switch to a faster/cheaper model such as `model: gemini-2.5-flash` and `thinking: low`.
  - Increase `timeout_minutes` (e.g., `timeout_minutes: 40`) for heavy Docker/Rust/Java builds.
  - Inspect the uploaded `pi-events.jsonl` and `token-usage.json` artifacts to see which tool calls drove token volume.

### 8. macOS / iOS / Xcode Projects Reported as Blocked
- **Cause**: Default runner is `ubuntu-latest`.
- **Fix**: Pass `runner: macos-latest` in the caller workflow's `with:` block.
