from __future__ import annotations

import py_compile
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "jsi-build-verify.yml"
SKILL_MD = REPO_ROOT / "skills" / "jeffs-automated-build-deploy-agent" / "SKILL.md"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_workflow_yaml_structure_and_outputs() -> None:
    wf = _load_workflow()
    on_block = wf.get("on") or wf.get(True)
    assert "workflow_call" in on_block
    assert "workflow_dispatch" in on_block

    call_outputs = set(on_block["workflow_call"]["outputs"].keys())
    job_outputs = set(wf["jobs"]["verify"]["outputs"].keys())
    assert call_outputs == job_outputs
    assert {"verification_status", "verification_summary", "total_tokens", "estimated_cost_usd"} <= call_outputs


def test_workflow_dispatch_thinking_options_match_documented_levels() -> None:
    wf = _load_workflow()
    on_block = wf.get("on") or wf.get(True)
    thinking_opts = set(on_block["workflow_dispatch"]["inputs"]["thinking"]["options"])
    assert {"off", "minimal", "low", "medium", "high", "xhigh", "max"} == thinking_opts
    shot_opts = set(on_block["workflow_dispatch"]["inputs"]["screenshot_mode"]["options"])
    assert {"artifact", "docs", "branch"} == shot_opts
    assert on_block["workflow_call"]["inputs"]["screenshot_mode"]["default"] == "artifact"


def test_workflow_actions_are_sha_pinned() -> None:
    sha_pattern = re.compile(r"^[^@]+@[0-9a-f]{40}$")
    for wf_path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        for job in wf["jobs"].values():
            for step in job.get("steps", []):
                uses = step.get("uses")
                if uses:
                    assert sha_pattern.match(uses), f"Action not SHA-pinned in {wf_path.name}: {uses}"


def test_all_python_scripts_compile_cleanly() -> None:
    py_files = [
        REPO_ROOT / "scripts" / "summarize_pi_usage.py",
        REPO_ROOT / "scripts" / "evaluate_verdict.py",
        REPO_ROOT / "skills" / "jeffs-automated-build-deploy-agent" / "scripts" / "api_verify.py",
        REPO_ROOT / "skills" / "jeffs-automated-build-deploy-agent" / "scripts" / "browser_verify.py",
        REPO_ROOT / "skills" / "jeffs-automated-build-deploy-agent" / "scripts" / "discover_top_repos.py",
    ]
    for path in py_files:
        assert path.exists(), f"Expected script missing: {path}"
        py_compile.compile(str(path), doraise=True)


def test_skill_frontmatter_and_bundled_scripts() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["name"] == "jeffs-automated-build-deploy-agent"
    assert frontmatter["description"]
