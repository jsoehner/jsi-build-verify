#!/usr/bin/env python3
"""Parse Pi (--mode json) JSONL event stream and report token & cost usage.

Reads a Pi JSONL log file, aggregates assistant turn + compaction token usage
and estimated costs, prints a human-readable summary, writes GitHub Actions
step outputs ($GITHUB_OUTPUT) and Markdown summary ($GITHUB_STEP_SUMMARY) when
available, and optionally writes a JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def parse_events(jsonl_path: Path) -> dict[str, Any]:
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "cost_input_usd": 0.0,
        "cost_output_usd": 0.0,
        "cost_cache_read_usd": 0.0,
        "cost_cache_write_usd": 0.0,
        "cost_total_usd": 0.0,
        "assistant_turns": 0,
        "compactions": 0,
        "tool_calls_total": 0,
        "tool_calls_by_name": {},
        "provider": "",
        "model": "",
        "stop_reason": "",
        "error_message": "",
        "final_text": "",
    }
    tool_counter: Counter[str] = Counter()

    def add_usage(usage: dict[str, Any] | None) -> None:
        if not isinstance(usage, dict):
            return
        inp = int(usage.get("input") or 0)
        out = int(usage.get("output") or 0)
        cr = int(usage.get("cacheRead") or 0)
        cw = int(usage.get("cacheWrite") or 0)
        tot = int(usage.get("totalTokens") or (inp + out + cr + cw))
        totals["input_tokens"] += inp
        totals["output_tokens"] += out
        totals["cache_read_tokens"] += cr
        totals["cache_write_tokens"] += cw
        totals["total_tokens"] += tot

        cost = usage.get("cost")
        if isinstance(cost, dict):
            totals["cost_input_usd"] += float(cost.get("input") or 0.0)
            totals["cost_output_usd"] += float(cost.get("output") or 0.0)
            totals["cost_cache_read_usd"] += float(cost.get("cacheRead") or 0.0)
            totals["cost_cache_write_usd"] += float(cost.get("cacheWrite") or 0.0)
            totals["cost_total_usd"] += float(cost.get("total") or 0.0)

    raw_bytes = jsonl_path.read_bytes()
    for raw_line in raw_bytes.split(b"\n"):
        line = raw_line.rstrip(b"\r").strip()
        if not line:
            continue
        try:
            event = json.loads(line.decode("utf-8"))
        except Exception:
            continue

        etype = event.get("type")
        if etype == "message_end":
            msg = event.get("message")
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                totals["assistant_turns"] += 1
                if msg.get("provider"):
                    totals["provider"] = str(msg["provider"])
                if msg.get("model"):
                    totals["model"] = str(msg["model"])
                if msg.get("stopReason"):
                    totals["stop_reason"] = str(msg["stopReason"])
                if msg.get("errorMessage"):
                    totals["error_message"] = str(msg["errorMessage"])
                add_usage(msg.get("usage"))

                content = msg.get("content")
                if isinstance(content, list):
                    text_parts = [
                        c.get("text", "")
                        for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    joined = "\n".join(p for p in text_parts if p).strip()
                    if joined:
                        totals["final_text"] = joined
        elif etype == "compaction_end":
            res = event.get("result")
            if isinstance(res, dict):
                totals["compactions"] += 1
                add_usage(res.get("usage"))
        elif etype == "tool_execution_start":
            tool_name = str(event.get("toolName") or "unknown")
            tool_counter[tool_name] += 1
            totals["tool_calls_total"] += 1

    totals["tool_calls_by_name"] = dict(tool_counter.most_common())
    return totals


def render_markdown(
    stats: dict[str, Any],
    provider_fallback: str,
    model_fallback: str,
    exit_code: int | None,
) -> str:
    provider = stats["provider"] or provider_fallback or "unknown"
    model = stats["model"] or model_fallback or "unknown"
    status_badge = "✅ Passed" if exit_code == 0 else (f"❌ Failed (exit {exit_code})" if exit_code is not None else "ℹ️ Completed")

    lines = [
        "## 🤖 JSI Automated Build & Verify — Token Usage Report",
        "",
        f"- **Status**: {status_badge}",
        f"- **Provider / Model**: `{provider}` / `{model}`",
        f"- **Assistant Turns**: {stats['assistant_turns']} (Compactions: {stats['compactions']})",
        f"- **Tool Calls**: {stats['tool_calls_total']}",
        "",
        "| Metric | Count / Cost |",
        "| :--- | ---: |",
        f"| Input Tokens | {stats['input_tokens']:,} |",
        f"| Output Tokens | {stats['output_tokens']:,} |",
        f"| Cache Read Tokens | {stats['cache_read_tokens']:,} |",
        f"| Cache Write Tokens | {stats['cache_write_tokens']:,} |",
        f"| **Total Tokens** | **{stats['total_tokens']:,}** |",
        f"| **Estimated Cost (USD)** | **${stats['cost_total_usd']:.4f}** |",
    ]

    if stats["tool_calls_by_name"]:
        breakdown = ", ".join(f"`{k}`: {v}" for k, v in stats["tool_calls_by_name"].items())
        lines.extend(["", f"**Tool Call Breakdown**: {breakdown}"])

    if stats["error_message"]:
        lines.extend(["", f"> [!WARNING]\n> **Agent Error**: `{stats['error_message']}`"])

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Pi JSONL token usage.")
    parser.add_argument("jsonl", type=Path, help="Path to Pi --mode json output file")
    parser.add_argument("--provider", default="", help="Fallback provider name")
    parser.add_argument("--model", default="", help="Fallback model name")
    parser.add_argument("--exit-code", type=int, default=None, help="Pi process exit code")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional path to write JSON report")
    parser.add_argument("--md-out", type=Path, default=None, help="Optional path to write Markdown report")
    args = parser.parse_args()

    if not args.jsonl.exists():
        print(f"[WARN] Pi JSONL file not found: {args.jsonl}", file=sys.stderr)
        return 0

    stats = parse_events(args.jsonl)
    md = render_markdown(stats, args.provider, args.model, args.exit_code)

    print(md)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

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
            fh.write(f"input_tokens={stats['input_tokens']}\n")
            fh.write(f"output_tokens={stats['output_tokens']}\n")
            fh.write(f"cache_read_tokens={stats['cache_read_tokens']}\n")
            fh.write(f"cache_write_tokens={stats['cache_write_tokens']}\n")
            fh.write(f"total_tokens={stats['total_tokens']}\n")
            fh.write(f"estimated_cost_usd={stats['cost_total_usd']:.6f}\n")
            fh.write(f"assistant_turns={stats['assistant_turns']}\n")
            fh.write(f"tool_calls_total={stats['tool_calls_total']}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
