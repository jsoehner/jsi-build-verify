# Repository Governance & Fork Guardrails

## 1. Forked Repository & Upstream Guardrail
- **Never unilaterally update a forked repository**: Forked repositories have an upstream source of truth. Avoid updating, modifying dependencies, or creating pull requests on a forked repository unless upstream is verified abandoned (archived, deleted, or >18 consecutive months without commits/releases).
- **In GitHub Actions CI**: Fork guardrails are enforced by the workflow `if: !github.event.repository.fork` condition. Do not attempt to run `~/memory_system/` scripts when running on GitHub-hosted runners.
- **In Local Workstations**: If `~/memory_system/check_fork_guardrail.py` exists, run `python3 ~/memory_system/check_fork_guardrail.py .` before modifying a repository and halt if it returns `BLOCKED`.

## 2. Memory Pre-Flight Protocol (Local Only)
- On local workstations where `~/memory_system/inspect_memory.py` is installed, query local lessons learned before making architectural decisions:
  ```bash
  python3 ~/memory_system/inspect_memory.py --preflight .
  ```
- Skip this step in ephemeral CI runners where `~/memory_system/` is not present.
