# Global Repository Governance & Memory Pre-Flight Guardrails

## 1. Forked Repository & Upstream Guardrail
- **Never unilaterally update a forked repository**: Forked repositories have an upstream source of truth. Skills and agents must avoid updating, modifying dependencies, or creating pull requests on a forked repository unless it is verified abandoned.
- **Refresh before deciding**: Always consider refreshing the fork against its upstream source first:
  ```bash
  gh repo sync --branch <default-branch>
  ```
- **Abandonment Test**: Upstream is abandoned ONLY if archived (`isArchived: true`), returns 404/deleted, or has had zero commits/releases for >18 consecutive months.
- **Automated Verification**: Before modifying any repository, execute:
  ```bash
  python3 ~/memory_system/check_fork_guardrail.py .
  ```
  If this returns exit code 1 (BLOCKED), halt unilateral updates immediately. Submit proposed changes upstream via PR or sync the fork.

## 2. Mandatory Memory Pre-Flight Protocol
- **Retrieve Lessons Learned Before Acting**: Before planning, refactoring, or modifying code, query the local memory system:
  ```bash
  python3 ~/memory_system/inspect_memory.py --preflight .
  # Or query by topic:
  python3 ~/memory_system/inspect_memory.py -q "<topic>"
  ```
- **Adhere to OKF Architectural Decisions**: Check and obey policies located in `~/memory_system/knowledge/okf/` (including Fork Governance, GitHub Actions SHA pinning, Dependabot cooldown, and Security Governance).
