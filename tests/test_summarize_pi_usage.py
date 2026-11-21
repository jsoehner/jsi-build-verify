from __future__ import annotations

import json
from pathlib import Path

import summarize_pi_usage


def _write_jsonl(path: Path, events: list[dict | str]) -> None:
    lines = [e if isinstance(e, str) else json.dumps(e) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_events_aggregates_turns_compactions_and_tools(tmp_path: Path) -> None:
    log = tmp_path / "pi-events.jsonl"
    _write_jsonl(
        log,
        [
            "not valid json at all",
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "provider": "google",
                    "model": "gemini-2.5-pro",
                    "stopReason": "error",
                    "errorMessage": "transient 429",
                    "usage": {
                        "input": 100,
                        "output": 20,
                        "cacheRead": 50,
                        "cacheWrite": 10,
                        "cost": {"input": 0.001, "output": 0.002, "total": 0.003},
                    },
                    "content": [{"type": "text", "text": "Retrying..."}],
                },
            },
            {"type": "tool_execution_start", "toolName": "bash"},
            {"type": "tool_execution_start", "toolName": "read"},
            {"type": "tool_execution_start", "toolName": "bash"},
            {
                "type": "compaction_end",
                "result": {
                    "usage": {
                        "input": 40,
                        "output": 10,
                        "totalTokens": 50,
                        "cost": {"total": 0.0005},
                    }
                },
            },
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "provider": "google",
                    "model": "gemini-2.5-pro",
                    "stopReason": "end_turn",
                    "usage": {
                        "input": 200,
                        "output": 30,
                        "totalTokens": 230,
                        "cost": {"total": 0.004},
                    },
                    "content": [{"type": "text", "text": "All checks passed."}],
                },
            },
        ],
    )

    stats = summarize_pi_usage.parse_events(log)
    assert stats["assistant_turns"] == 2
    assert stats["compactions"] == 1
    assert stats["input_tokens"] == 340
    assert stats["output_tokens"] == 60
    assert stats["cache_read_tokens"] == 50
    assert stats["cache_write_tokens"] == 10
    assert stats["total_tokens"] == 460
    assert abs(stats["cost_total_usd"] - 0.0075) < 1e-9
    assert stats["tool_calls_total"] == 3
    assert stats["tool_calls_by_name"] == {"bash": 2, "read": 1}
    assert stats["final_text"] == "All checks passed."
    assert stats["error_message"] == ""


def test_main_missing_jsonl_writes_zeroed_outputs(tmp_path: Path, monkeypatch) -> None:
    gh_out = tmp_path / "gh_output.txt"
    gh_sum = tmp_path / "gh_summary.md"
    json_out = tmp_path / "usage.json"
    md_out = tmp_path / "usage.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(gh_sum))

    rc = summarize_pi_usage.main(
        [
            str(tmp_path / "nonexistent.jsonl"),
            "--provider",
            "google",
            "--model",
            "gemini-2.5-pro",
            "--exit-code",
            "1",
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ]
    )
    assert rc == 0
    assert "total_tokens=0\n" in gh_out.read_text(encoding="utf-8")
    assert "estimated_cost_usd=0.000000\n" in gh_out.read_text(encoding="utf-8")
    assert "Failed (exit 1)" in md_out.read_text(encoding="utf-8")
    assert json.loads(json_out.read_text(encoding="utf-8"))["total_tokens"] == 0
