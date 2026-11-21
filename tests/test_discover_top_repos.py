from __future__ import annotations

import json
import subprocess

import discover_top_repos

SAMPLE_NODES = [
    {
        "name": "zeta",
        "nameWithOwner": "owner/zeta",
        "isPrivate": False,
        "pushedAt": "2026-01-02T00:00:00Z",
        "primaryLanguage": {"name": "Python"},
        "defaultBranchRef": {"name": "main", "target": {"history": {"totalCount": 50}}},
    },
    {
        "name": "Alpha",
        "nameWithOwner": "owner/Alpha",
        "isPrivate": True,
        "pushedAt": "2026-01-03T00:00:00Z",
        "primaryLanguage": None,
        "defaultBranchRef": {"name": "master", "target": {"history": {"totalCount": 50}}},
    },
    {
        "name": "empty-repo",
        "nameWithOwner": "owner/empty-repo",
        "isPrivate": False,
        "pushedAt": "2026-01-01T00:00:00Z",
        "primaryLanguage": None,
        "defaultBranchRef": None,
    },
]


def test_rank_repositories_sorts_by_commits_and_name() -> None:
    ranked = discover_top_repos.rank_repositories(SAMPLE_NODES, top=2)
    assert [r["name"] for r in ranked] == ["Alpha", "zeta"]
    assert ranked[0]["primaryLanguage"] == "None"
    assert ranked[0]["defaultBranch"] == "master"


def test_rank_repositories_handles_empty_repo() -> None:
    ranked = discover_top_repos.rank_repositories(SAMPLE_NODES, top=10)
    empty = [r for r in ranked if r["name"] == "empty-repo"][0]
    assert empty["commits"] == 0
    assert empty["defaultBranch"] == "main"


def test_main_json_and_tsv_output(monkeypatch, capsys) -> None:
    payload = {"data": {"user": {"repositories": {"nodes": SAMPLE_NODES}}}}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(payload), stderr=""),
    )

    assert discover_top_repos.main(["--owner", "owner", "--top", "2", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in parsed] == ["Alpha", "zeta"]

    assert discover_top_repos.main(["--owner", "owner", "--top", "2"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("1\t50\tAlpha\tprivate\tNone\t")


def test_main_handles_graphql_missing_user(monkeypatch, capsys) -> None:
    payload = {"data": {"user": None}, "errors": [{"message": "Could not resolve to a User"}]}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(payload), stderr=""),
    )

    assert discover_top_repos.main(["--owner", "nobody"]) == 1
    assert "Could not resolve to a User" in capsys.readouterr().err
