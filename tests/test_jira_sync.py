"""scripts/jira_sync.py: every guardrail, against a pretend Jira (no network).

The rule: it touches only Allen Matthew's issues in the one configured project,
only by adding a comment or moving an issue forward, and only with --apply.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import jira_sync as js  # noqa: E402

ALLEN = "acc-allen"
OTHER = "acc-someone-else"


def config(**changes) -> js.Config:
    values = dict(base_url="https://revealer.atlassian.net", project_key="SOCO", allen_account_id=ALLEN,
                  allen_display_name="Allen Matthew", issues={"ENG-12": ["SOCO-1"], "ENG-13": ["SOCO-2"]},
                  transitions={"Built": "In Review", "Passed": "Done"},
                  jira_status_order=["To Do", "In Progress", "In Review", "Done"], max_writes_per_run=20)
    values.update(changes)
    cfg = js.Config(**values)
    cfg.validate()
    return cfg


class FakeJira:
    """Answers like Jira Cloud; records every request."""

    def __init__(self, me=ALLEN, issues=None, comments=None, status="In Progress"):
        self.me = me
        self.calls: list[tuple[str, str, object]] = []
        self.issues = issues or {
            "SOCO-1": {"project": "SOCO", "assignee": ALLEN, "name": "Allen Matthew"},
            "SOCO-2": {"project": "SOCO", "assignee": ALLEN, "name": "Allen Matthew"},
        }
        self.comments = comments or {}
        self.status = status

    def __call__(self, method, url, headers, body):
        path = url.split(".atlassian.net", 1)[1].split("?", 1)[0]
        self.calls.append((method, path, json.loads(body) if body else None))
        if path == "/rest/api/3/myself":
            return 200, {"accountId": self.me, "displayName": "Allen Matthew" if self.me == ALLEN else "Someone"}
        key = path.split("/")[5] if path.startswith("/rest/api/3/issue/") else None
        if path.endswith("/comment"):
            return (201, {}) if method == "POST" else (200, self.comments.get(key, {"comments": []}))
        if path.endswith("/transitions"):
            if method == "POST":
                return 204, None
            return 200, {"transitions": [{"id": "31", "to": {"name": "In Review"}}, {"id": "41", "to": {"name": "Done"}}]}
        if key:
            i = self.issues[key]
            return 200, {"key": key, "fields": {"project": {"key": i["project"]}, "status": {"name": self.status},
                                                "assignee": {"accountId": i["assignee"], "displayName": i["name"]}}}
        return 404, {}

    def writes(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


def jira(fake, cfg=None, apply=True, tmp_path=None) -> js.Jira:
    j = js.Jira(cfg or config(), apply=apply, transport=fake, email="allen@example.com", token="t")
    if tmp_path is not None:
        j.audit_path = tmp_path / "audit.jsonl"
    return j


# --- configuration ------------------------------------------------------------------------------


@pytest.mark.parametrize("change, message", [
    ({"base_url": "https://evil.example.com"}, "base_url"),
    ({"project_key": ""}, "project_key"),
    ({"allen_account_id": ""}, "allen_account_id"),
    ({"issues": {"ENG-12": ["OTHER-5"]}}, "not an issue of project SOCO"),
    ({"issues": {"ENG-12": ["SOCO-1"], "ENG-13": ["SOCO-1"]}}, "same issue"),
    ({"transitions": {"Built": "Closed"}}, "jira_status_order"),
    ({"max_writes_per_run": 500}, "max_writes_per_run"),
])
def test_a_bad_configuration_refuses_to_run(change, message) -> None:
    with pytest.raises(js.GuardError, match=message):
        config(**change)


def test_a_blank_settings_file_refuses_and_check_alone_runs_without_an_account(tmp_path) -> None:
    blank = tmp_path / "jira_sync.toml"
    blank.write_text('base_url = ""
project_key = ""
allen_account_id = ""
', encoding="utf-8")
    with pytest.raises(js.GuardError):
        js.Config.load(blank)
    no_account = tmp_path / "no_account.toml"
    no_account.write_text('base_url = "https://mysoco.atlassian.net"
project_key = "SRE"
allen_account_id = ""
',
                          encoding="utf-8")
    with pytest.raises(js.GuardError, match="allen_account_id"):
        js.Config.load(no_account)
    assert js.Config.load(no_account, need_account=False).project_key == "SRE"  # `check` only


# --- the request guard --------------------------------------------------------------------------


@pytest.mark.parametrize("method, path", [
    ("DELETE", "/rest/api/3/issue/SOCO-1"),
    ("PUT", "/rest/api/3/issue/SOCO-1"),  # editing fields
    ("POST", "/rest/api/3/issue"),  # creating an issue
    ("PUT", "/rest/api/3/issue/SOCO-1/assignee"),
    ("POST", "/rest/api/3/issue/OTHER-1/comment"),  # another project
    ("GET", "/rest/api/3/issue/OTHER-1"),
    ("POST", "/rest/api/3/issueLink"),
    ("POST", "/rest/api/3/issue/bulk"),
    ("GET", "/rest/api/3/project/OTHER"),
])
def test_only_the_listed_requests_are_ever_sent(method, path) -> None:
    fake = FakeJira()
    with pytest.raises(js.GuardError, match="not an allowed request"):
        jira(fake).request(method, path)
    assert fake.calls == []


def test_no_write_in_a_dry_run(tmp_path) -> None:
    fake = FakeJira()
    j = jira(fake, apply=False, tmp_path=tmp_path)
    j.verify_issue("SOCO-1")
    with pytest.raises(js.GuardError, match="dry run"):
        j.request("POST", "/rest/api/3/issue/SOCO-1/comment", payload={})
    assert fake.writes() == []


def test_no_write_to_an_issue_not_verified_in_this_run() -> None:
    fake = FakeJira()
    with pytest.raises(js.GuardError, match="not verified"):
        jira(fake).request("POST", "/rest/api/3/issue/SOCO-1/comment", payload={})
    assert fake.writes() == []


def test_the_token_must_be_allens(tmp_path) -> None:
    fake = FakeJira(me=OTHER)
    with pytest.raises(js.GuardError, match="token belongs to"):
        js.run_sync(jira(fake, tmp_path=tmp_path), "abc1234")
    assert fake.writes() == []


def test_an_issue_assigned_to_someone_else_is_skipped(tmp_path) -> None:
    fake = FakeJira(issues={"SOCO-1": {"project": "SOCO", "assignee": OTHER, "name": "Someone"},
                            "SOCO-2": {"project": "SOCO", "assignee": ALLEN, "name": "Allen Matthew"}})
    report = js.run_sync(jira(fake, tmp_path=tmp_path), "abc1234")
    assert any(line.startswith("SKIP skip SOCO-1: assigned to") for line in report)
    assert all("SOCO-1" not in p for _, p in fake.writes())
    assert any("SOCO-2" in p for _, p in fake.writes())
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert any(a["action"] == "skipped" and a["issue"] == "SOCO-1" for a in audit)


def test_an_issue_moved_to_another_project_is_skipped(tmp_path) -> None:
    fake = FakeJira(issues={"SOCO-1": {"project": "OTHER", "assignee": ALLEN, "name": "Allen Matthew"},
                            "SOCO-2": {"project": "SOCO", "assignee": ALLEN, "name": "Allen Matthew"}})
    js.run_sync(jira(fake, tmp_path=tmp_path), "abc1234")
    assert all("SOCO-1" not in p for _, p in fake.writes())


def test_a_task_that_is_not_allens_is_refused(tmp_path, monkeypatch) -> None:
    owners = js.build_list_owners()
    monkeypatch.setattr(js, "build_list_owners", lambda: {**owners, "ENG-12": "Aravinth"})
    fake = FakeJira()
    report = js.run_sync(jira(fake, tmp_path=tmp_path), "abc1234")
    assert any("REFUSED ENG-12: Build List owner" in line for line in report)
    assert all("SOCO-1" not in p for _, p in fake.writes())


# --- what it writes -----------------------------------------------------------------------------


def test_a_comment_then_a_forward_move_and_nothing_else(tmp_path) -> None:
    fake = FakeJira()
    report = js.run_sync(jira(fake, tmp_path=tmp_path), "abc1234")
    assert set(fake.writes()) == {("POST", "/rest/api/3/issue/SOCO-1/comment"), ("POST", "/rest/api/3/issue/SOCO-1/transitions"),
                                  ("POST", "/rest/api/3/issue/SOCO-2/comment"), ("POST", "/rest/api/3/issue/SOCO-2/transitions")}
    body = next(b for m, p, b in fake.calls if p.endswith("SOCO-1/comment") and m == "POST")
    text = json.dumps(body)
    assert "ENG-12 is Built" in text and "[reco-sync ENG-12 " in text and "Claude" not in text
    assert any("moved 'In Progress' -> 'In Review'" in line for line in report)


def test_the_same_update_is_never_posted_twice(tmp_path) -> None:
    task = js.read_tasks()["ENG-12"]
    marker = f"[reco-sync ENG-12 {task.fingerprint}]"
    fake = FakeJira(comments={"SOCO-1": {"comments": [{"body": {"content": [{"text": marker}]}}]}})
    report = js.run_sync(jira(fake, cfg=config(transitions={}), tmp_path=tmp_path), "abc1234")
    assert "SOCO-1 (ENG-12): up to date (Built)" in report
    assert ("POST", "/rest/api/3/issue/SOCO-1/comment") not in fake.writes()


def test_never_moves_an_issue_backwards(tmp_path) -> None:
    fake = FakeJira(status="Done")
    report = js.run_sync(jira(fake, tmp_path=tmp_path), "abc1234")
    assert not any(p.endswith("/transitions") for m, p in fake.writes())
    assert any("only forward" in line for line in report)


def test_a_run_stops_at_max_writes(tmp_path) -> None:
    fake = FakeJira()
    with pytest.raises(js.GuardError, match="max_writes_per_run"):
        js.run_sync(jira(fake, cfg=config(max_writes_per_run=1), tmp_path=tmp_path), "abc1234")
    assert len(fake.writes()) == 1


def test_a_dry_run_reports_and_writes_nothing(tmp_path) -> None:
    fake = FakeJira()
    report = js.run_sync(jira(fake, apply=False, tmp_path=tmp_path), "abc1234")
    assert fake.writes() == [] and any("would comment" in line for line in report)


# --- matching differently worded tasks ----------------------------------------------------------


TASKS = {
    "ENG-13": "M2 retrieval Retrieval method one quotas Build a pool of 300 candidates interest follows trending popular round-robin",
    "ENG-14": "M2 retrieval Retrieval method two similar posts computed nightly vector cosine profile engaged posts",
    "ENG-16": "M8 promoter score Promoter score both methods reach content quality consistency net commerce conversion",
}


def test_a_reworded_issue_matches_its_task() -> None:
    issues = [("SOCO-7", "Candidate pool with quotas from interests, follows, trending and popular posts\n"),
              ("SOCO-8", "Nightly job: similar posts per user using cosine on post vectors\n"),
              ("SOCO-9", "Creator/promoter scoring (reach, quality, commerce) - two methods\n")]
    got = {m.issue: (m.eng, m.confident) for m in js.match_issues(issues, TASKS)}
    assert got == {"SOCO-7": ("ENG-13", True), "SOCO-8": ("ENG-14", True), "SOCO-9": ("ENG-16", True)}


def test_an_eng_id_in_the_issue_wins() -> None:
    [m] = js.match_issues([("SOCO-3", "ENG 14 - follow-ups\nsome text about quotas")], TASKS)
    assert (m.eng, m.score, m.confident) == ("ENG-14", 1.0, True)


def test_an_unclear_issue_is_not_confident() -> None:
    [m] = js.match_issues([("SOCO-4", "Weekly sync meeting notes\n")], TASKS)
    assert not m.confident


def test_approve_copies_only_confident_matches(tmp_path) -> None:
    settings = tmp_path / "jira_sync.toml"
    settings.write_text('base_url = "https://revealer.atlassian.net"\nproject_key = "SOCO"\nallen_account_id = "acc-allen"\n'
                        'jira_status_order = ["To Do", "Done"]\n[transitions]\n[issues]\n', encoding="utf-8")
    proposals = tmp_path / "proposed.json"
    proposals.write_text(json.dumps([
        {"issue": "SOCO-7", "eng": "ENG-13", "confident": True},
        {"issue": "SOCO-4", "eng": "ENG-14", "confident": False},
        {"issue": "SOCO-9", "eng": "ENG-16", "confident": True},
    ]), encoding="utf-8")
    js.approve(js.Config.load(settings), settings, proposals)
    cfg = js.Config.load(settings)
    assert cfg.issues == {"ENG-13": ["SOCO-7"], "ENG-16": ["SOCO-9"]}
