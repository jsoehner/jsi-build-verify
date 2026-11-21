# Controlling LLM API Spend in `jsi-build-verify`

Because `jsi-build-verify` runs an AI coding agent against your configured LLM provider API (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.), every triggered workflow run incurs API billing. Controlling spend takes **3 quick steps**.

---

## 1. Use a Low-Cost Model & `workflow_dispatch`-Only Trigger (2-Minute YAML Setup)

In your repository's `.github/workflows/verify.yml`, remove the automatic `pull_request:` trigger and switch to `model: gemini-2.5-flash` with `thinking: low`:

```yaml
name: JSI Build & Functional Verification

on:
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  verify:
    uses: jsoehner/jsi-build-verify/.github/workflows/jsi-build-verify.yml@v1.0.1
    with:
      workflow_ref: v1.0.1
      model: gemini-2.5-flash
      thinking: low
      commit_mode: report-only
      fail_on_error: true
      comment_on_pr: false
    secrets:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      OSS_MTLS_CLIENT_CERT: ${{ secrets.OSS_MTLS_CLIENT_CERT }}
      OSS_MTLS_CLIENT_KEY: ${{ secrets.OSS_MTLS_CLIENT_KEY }}
```

**Why this helps:**
- **Zero accidental runs:** Nothing runs until you explicitly click **Actions → JSI Build & Functional Verification → Run workflow** (or run `gh workflow run verify.yml`).
- **Lower token & reasoning cost:** `gemini-2.5-flash` + `thinking: low` uses significantly cheaper tokens and fewer reasoning turns than `gemini-3.1-pro-preview` + `medium`.
- **Repo-wide override option:** Instead of editing YAML across many repos, you can set repository or organization Actions variables `PI_MODEL=gemini-2.5-flash` and `PI_PROVIDER=google`.

---

## 2. Set a Hard Spend Cap / Quota at Your API Provider (3 Minutes)

GitHub Actions cannot enforce billing caps on external API keys. Configure a cap directly in your provider console:

### Google Gemini (`GEMINI_API_KEY`)
1. Open **Google Cloud Console** for the project linked to your Google AI Studio key.
2. **Budget Alert:** Go to **Billing → Budgets & alerts → Create budget**, set a monthly dollar amount (e.g., `$10/month`), and add email alerts at `50%`, `90%`, and `100%`.
3. **Hard Rate/Daily Cap:** Go to **APIs & Services → Enabled APIs & services → Generative Language API → Quotas & System Limits**, and cap daily requests (`GenerateContent` requests per day) to stop runaway loops automatically.

### Other Providers
- **Anthropic (`ANTHROPIC_API_KEY`):** Console → **Settings → Limits** → set a monthly spend limit.
- **OpenAI (`OPENAI_API_KEY`):** Platform → **Settings → Billing → Limits** → set a hard monthly budget.
- **OpenRouter (`OPENROUTER_API_KEY`):** **Keys → Edit Key → Credit Limit** → set a per-key dollar cap (ideal for CI keys).

---

## 3. Monitor Actual Spend Per Run

Every run automatically prints a **Token Usage & Estimated USD Cost** table in the GitHub Actions Step Summary and uploads `token-usage.json` as an artifact.

| Reference Repo | Stack | Model / Thinking | Observed Tokens | Observed Cost |
| :--- | :--- | :--- | ---: | ---: |
| `jsoehner/WASM-demo` | Rust / WASM + Browser UI | `gemini-3.1-pro-preview` / `medium` | 278,484 | `$0.2331` |
| `jsoehner/dbsc-express-demo` | Node.js / Express + API + Browser UI | `gemini-3.1-pro-preview` / `medium` | 459,559 | `$0.4034` |

> [!TIP]
> You can also add a short `.jsi-verify.yml` in the repo root (explicit `build`, `test`, `start`, and `checks`) so the agent skips stack discovery turns and finishes in fewer tokens.
