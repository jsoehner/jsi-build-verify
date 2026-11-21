#!/usr/bin/env python3
"""Evaluate structured verification verdict produced by the Pi verification agent.

Reads a JSON verdict file (e.g. /tmp/jsi-verify/verdict.json), normalizes its
status, renders a Markdown summary, writes GitHub Actions outputs
($GITHUB_OUTPUT) and step summary ($GITHUB_STEP_SUMMARY) when available, and
optionally exits non-zero when verification did not pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

VALID_STATUSES = {"pass", "fail", "blocked"}

STATUS_BADGES = {
    "pass": "✅ Passed",
    "fail": "❌ Failed",
    "blocked": "⚠️ Blocked",
    "error": "💥 Error",
}

CHECK_BADGES = {
    "pass": "✅",
    "fail": "❌",
    "skip": "⏭️",
    "blocked": "⚠️",
}


def load_verdict(verdict_path: Path, pi_exit_code: int = 0) -> dict[str, Any]:
    """Load and normalize a verdict JSON file."""
    base: dict[str, Any] = {
        "status": "error",
        "summary": "",
        "checks": [],
        "failure_reason": "",
        "pi_exit_code": pi_exit_code,
    }

    if not verdict_path.exists():
        base["failure_reason"] = f"Agent did not produce verdict file: {verdict_path}"
        base["summary"] = (
            f"Verification failed (Pi exit {pi_exit_code}; missing verdict.json)"
            if pi_exit_code != 0
            else "Verification failed (missing verdict.json)"
        )
        return base

    try:
        raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    except Exception as exc:
        base["failure_reason"] = f"Invalid verdict JSON: {exc}"
        base["summary"] = "Verification failed (invalid verdict.json)"
        return base

    if not isinstance(raw, dict):
        base["failure_reason"] = "Verdict JSON root must be an object"
        base["summary"] = "Verification failed (malformed verdict.json)"
        return base

    status = str(raw.get("status") or "").strip().lower()
    if status not in VALID_STATUSES:
        base["failure_reason"] = (
            f"Invalid verdict status {raw.get('status')!r}; expected one of {sorted(VALID_STATUSES)}"
        )
        base["summary"] = "Verification failed (invalid verdict status)"
        return base

    summary = str(raw.get("summary") or "").strip()
    failure_reason = str(raw.get("failure_reason") or "").strip()

    raw_checks = raw.get("checks")
    checks: list[dict[str, str]] = []
    if isinstance(raw_checks, list):
        for item in raw_checks:
            if isinstance(item, dict):
                checks.append(
                    {
                        "name": str(item.get("name") or "unnamed").strip(),
                        "status": str(item.get("status") or "unknown").strip().lower(),
                        "details": str(item.get("details") or "").strip(),
                    }
                )

    if pi_exit_code != 0 and status == "pass":
        status = "fail"
        note = f"Pi process exited with code {pi_exit_code} despite pass verdict"
        failure_reason = f"{failure_reason}; {note}" if failure_reason else note

    if not summary:
        summary = f"Verification {status}"

    return {
        "status": status,
        "summary": summary,
        "checks": checks,
        "failure_reason": failure_reason,
        "pi_exit_code": pi_exit_code,
    }


def discover_screenshots(screenshots_dir: Path | None) -> list[dict[str, Any]]:
    """Find PNG screenshots under screenshots_dir sorted by relative path."""
    if not screenshots_dir or not screenshots_dir.exists():
        return []
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for p in sorted(screenshots_dir.rglob("*.png")):
        resolved = p.resolve()
        if resolved in seen or not p.is_file():
            continue
        seen.add(resolved)
        found.append(
            {
                "name": p.name,
                "rel_path": p.relative_to(screenshots_dir).as_posix(),
                "path": str(p),
                "bytes": p.stat().st_size,
            }
        )
    return found


def render_verdict_markdown(
    verdict: dict[str, Any],
    *,
    screenshots: list[dict[str, Any]] | None = None,
    screenshot_base_url: str = "",
    screenshot_url_suffix: str = "",
    artifact_url: str = "",
) -> str:
    """Render a normalized verdict dict as GitHub-flavored Markdown."""
    status = verdict.get("status", "error")
    badge = STATUS_BADGES.get(status, f"ℹ️ {status}")
    summary = verdict.get("summary") or "No summary provided."
    failure_reason = verdict.get("failure_reason") or ""
    checks = verdict.get("checks") or []

    lines = [
        "## 🧪 JSI Build & Functional Verification — Verdict",
        "",
        f"- **Result**: {badge} (`{status}`)",
        f"- **Summary**: {summary}",
    ]

    if failure_reason:
        lines.extend(["", f"> [!CAUTION]\n> **Reason**: {failure_reason}"])

    if checks:
        lines.extend(
            [
                "",
                "| Check | Status | Details |",
                "| :--- | :---: | :--- |",
            ]
        )
        for chk in checks:
            c_status = chk.get("status", "unknown")
            c_badge = CHECK_BADGES.get(c_status, "ℹ️")
            c_name = chk.get("name", "unnamed").replace("|", "\\|")
            c_details = chk.get("details", "").replace("\n", " ").replace("|", "\\|")
            lines.append(f"| `{c_name}` | {c_badge} `{c_status}` | {c_details} |")

    if screenshots:
        lines.extend(["", "### 📸 Browser Screenshots", ""])
        if screenshot_base_url:
            base = screenshot_base_url.rstrip("/")
            for shot in screenshots:
                name = shot["name"]
                img_url = f"{base}/{name}{screenshot_url_suffix}"
                lines.extend([f"#### `{name}`", "", f"![{name}]({img_url})", ""])
        else:
            lines.extend(["| Screenshot | Size |", "| :--- | ---: |"])
            for shot in screenshots:
                kb = shot["bytes"] / 1024.0
                rel = shot["rel_path"].replace("|", "\\|")
                lines.append(f"| `{rel}` | {kb:.1f} KB |")
            if artifact_url:
                lines.extend(["", f"Download all screenshots from the [workflow run artifacts]({artifact_url})."])

    return "\n".join(lines).rstrip() + "\n"


def _sanitize_output_value(value: str) -> str:
    return " ".join(value.splitlines()).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate JSI verification verdict.json.")
    parser.add_argument("verdict", type=Path, help="Path to verdict.json")
    parser.add_argument("--pi-exit-code", type=int, default=0, help="Pi process exit code")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional path for normalized JSON verdict")
    parser.add_argument("--md-out", type=Path, default=None, help="Optional path for Markdown verdict summary")
    parser.add_argument(
        "--screenshots-dir",
        type=Path,
        default=None,
        help="Optional directory to scan for captured PNG screenshots",
    )
    parser.add_argument(
        "--screenshot-base-url",
        default="",
        help="Optional base URL (or relative path) to embed screenshots inline in Markdown",
    )
    parser.add_argument(
        "--screenshot-url-suffix",
        default="",
        help="Optional URL suffix appended to inline screenshot URLs (e.g. ?raw=true)",
    )
    parser.add_argument(
        "--artifact-url",
        default="",
        help="Optional GitHub Actions run artifacts URL for artifact-mode screenshot links",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero if verification status is not 'pass'",
    )
    args = parser.parse_args(argv)

    verdict = load_verdict(args.verdict, pi_exit_code=args.pi_exit_code)
    screenshots = discover_screenshots(args.screenshots_dir)
    verdict["screenshots"] = screenshots
    md = render_verdict_markdown(
        verdict,
        screenshots=screenshots,
        screenshot_base_url=args.screenshot_base_url,
        screenshot_url_suffix=args.screenshot_url_suffix,
        artifact_url=args.artifact_url,
    )
    print(md)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")

    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(md, encoding="utf-8")

    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        with open(gh_summary, "a", encoding="utf-8") as fh:
            fh.write("\n" + md)

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"verification_status={verdict['status']}\n")
            fh.write(f"verification_summary={_sanitize_output_value(verdict['summary'])}\n")
            fh.write(f"screenshot_count={len(screenshots)}\n")

    if args.fail_on_error and verdict["status"] != "pass":
        print(
            f"::error title=Verification {verdict['status'].upper()}::"
            f"{_sanitize_output_value(verdict['failure_reason'] or verdict['summary'])}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
