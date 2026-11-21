from __future__ import annotations

import json
from pathlib import Path

import evaluate_verdict


def test_load_verdict_pass(tmp_path: Path) -> None:
    vf = tmp_path / "verdict.json"
    vf.write_text(
        json.dumps(
            {
                "status": "pass",
                "summary": "All build, unit, API, and browser checks passed.",
                "checks": [
                    {"name": "build", "status": "pass", "details": "npm run build ok"},
                    {"name": "api", "status": "pass", "details": "GET /health -> 200"},
                ],
                "failure_reason": "",
            }
        ),
        encoding="utf-8",
    )
    res = evaluate_verdict.load_verdict(vf, pi_exit_code=0)
    assert res["status"] == "pass"
    assert len(res["checks"]) == 2
    assert res["failure_reason"] == ""


def test_load_verdict_downgrades_pass_when_pi_crashed(tmp_path: Path) -> None:
    vf = tmp_path / "verdict.json"
    vf.write_text(json.dumps({"status": "pass", "summary": "Looks ok"}), encoding="utf-8")
    res = evaluate_verdict.load_verdict(vf, pi_exit_code=2)
    assert res["status"] == "fail"
    assert "exit" in res["failure_reason"].lower()


def test_load_verdict_missing_file(tmp_path: Path) -> None:
    res = evaluate_verdict.load_verdict(tmp_path / "missing.json", pi_exit_code=0)
    assert res["status"] == "error"
    assert "did not produce verdict file" in res["failure_reason"]


def test_load_verdict_invalid_json(tmp_path: Path) -> None:
    vf = tmp_path / "verdict.json"
    vf.write_text("{not valid json", encoding="utf-8")
    res = evaluate_verdict.load_verdict(vf)
    assert res["status"] == "error"
    assert "Invalid verdict JSON" in res["failure_reason"]


def test_load_verdict_invalid_status(tmp_path: Path) -> None:
    vf = tmp_path / "verdict.json"
    vf.write_text(json.dumps({"status": "maybe", "summary": "unsure"}), encoding="utf-8")
    res = evaluate_verdict.load_verdict(vf)
    assert res["status"] == "error"
    assert "Invalid verdict status" in res["failure_reason"]


def test_main_fail_on_error_and_github_outputs(tmp_path: Path, monkeypatch) -> None:
    vf = tmp_path / "verdict.json"
    vf.write_text(
        json.dumps(
            {
                "status": "fail",
                "summary": "Unit tests failed\n2 assertions broken",
                "checks": [{"name": "pytest", "status": "fail", "details": "2 failed"}],
                "failure_reason": "test_auth failed",
            }
        ),
        encoding="utf-8",
    )
    gh_out = tmp_path / "gh_output.txt"
    gh_sum = tmp_path / "gh_summary.md"
    json_out = tmp_path / "out" / "norm.json"
    md_out = tmp_path / "out" / "verdict.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(gh_sum))

    rc = evaluate_verdict.main(
        [
            str(vf),
            "--pi-exit-code",
            "0",
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
            "--fail-on-error",
        ]
    )
    assert rc == 1
    out_text = gh_out.read_text(encoding="utf-8")
    assert "verification_status=fail\n" in out_text
    assert "verification_summary=Unit tests failed 2 assertions broken\n" in out_text
    assert "test_auth failed" in gh_sum.read_text(encoding="utf-8")
    assert json.loads(json_out.read_text(encoding="utf-8"))["status"] == "fail"
    assert "| `pytest` | ❌ `fail` | 2 failed |" in md_out.read_text(encoding="utf-8")


def test_main_passes_without_fail_flag_or_on_pass(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    vf = tmp_path / "verdict.json"
    vf.write_text(json.dumps({"status": "pass", "summary": "All green"}), encoding="utf-8")
    assert evaluate_verdict.main([str(vf), "--fail-on-error"]) == 0


def test_screenshots_artifact_and_inline_rendering(tmp_path: Path, monkeypatch) -> None:
    vf = tmp_path / "verdict.json"
    vf.write_text(json.dumps({"status": "pass", "summary": "UI verified"}), encoding="utf-8")
    shots_dir = tmp_path / "verify"
    (shots_dir / "screenshots").mkdir(parents=True)
    (shots_dir / "screenshots" / "00-initial.png").write_bytes(b"\x89PNG" + b"0" * 2044)
    (shots_dir / "screenshots" / "01-click-login.png").write_bytes(b"\x89PNG" + b"1" * 1020)

    gh_out = tmp_path / "gh_output.txt"
    md_artifact = tmp_path / "artifact.md"
    md_inline = tmp_path / "inline.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    rc = evaluate_verdict.main(
        [
            str(vf),
            "--screenshots-dir",
            str(shots_dir),
            "--artifact-url",
            "https://github.com/owner/repo/actions/runs/99#artifacts",
            "--md-out",
            str(md_artifact),
        ]
    )
    assert rc == 0
    assert "screenshot_count=2\n" in gh_out.read_text(encoding="utf-8")
    art_text = md_artifact.read_text(encoding="utf-8")
    assert "### 📸 Browser Screenshots" in art_text
    assert "`screenshots/00-initial.png`" in art_text
    assert "https://github.com/owner/repo/actions/runs/99#artifacts" in art_text

    rc2 = evaluate_verdict.main(
        [
            str(vf),
            "--screenshots-dir",
            str(shots_dir),
            "--screenshot-base-url",
            "https://github.com/owner/repo/blob/jsi-verify-screenshots/99",
            "--screenshot-url-suffix",
            "?raw=true",
            "--md-out",
            str(md_inline),
        ]
    )
    assert rc2 == 0
    inline_text = md_inline.read_text(encoding="utf-8")
    assert "![00-initial.png](https://github.com/owner/repo/blob/jsi-verify-screenshots/99/00-initial.png?raw=true)" in inline_text
    assert "![01-click-login.png](https://github.com/owner/repo/blob/jsi-verify-screenshots/99/01-click-login.png?raw=true)" in inline_text
