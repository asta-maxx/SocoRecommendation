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
    values = dict(base_url="https://mysoco.atlassian.net", project_key="SRE", allen_account_id=ALLEN,
                  allen_display_name="Allen Matthew", issues={"SRE-1": ["ENG-12"], "SRE-2": ["ENG-13", "ENG-15"]},
                  transitions={"Built": "In Progress", "Passed": "Done", "In progress": "In Progress"},
                  jira_status_order=["To Do", "In Progress", "Done"], max_writes_per_run=20, attach_proofs=False)
    values.update(changes)
    cfg = js.Config(**values)
    cfg.validate()
    return cfg


class FakeJira:
    """Answers like Jira Cloud; records every request."""

    def __init__(self, me=ALLEN, issues=None, comments=None, status="To Do", attachments=None):
        self.me = me
        self.calls: list[tuple[str, str, object]] = []
        self.headers: list[dict[str, str]] = []
        self.attachments = attachments or {}
        self.issues = issues or {
            "SRE-1": {"project": "SRE", "assignee": ALLEN, "name": "Allen Matthew"},
            "SRE-2": {"project": "SRE", "assignee": ALLEN, "name": "Allen Matthew"},
        }
        self.comments = comments or {}
        self.status = status

    def __call__(self, method, url, headers, body):
        path = url.split(".atlassian.net", 1)[1].split("?", 1)[0]
        self.headers.append(headers)
        is_json = headers.get("Content-Type") == "application/json"
        self.calls.append((method, path, (json.loads(body) if is_json else body) if body else None))
        if path == "/rest/api/3/myself":
            return 200, {"accountId": self.me, "displayName": "Allen Matthew" if self.me == ALLEN else "Someone"}
        key = path.split("/")[5] if path.startswith("/rest/api/3/issue/") else None
        if path.endswith("/attachments"):
            return 200, [{"filename": "x"}]
        if path.endswith("/comment"):
            return (201, {}) if method == "POST" else (200, self.comments.get(key, {"comments": []}))
        if path.endswith("/transitions"):
            if method == "POST":
                return 204, None
            return 200, {"transitions": [{"id": "21", "to": {"name": "In Progress"}}, {"id": "31", "to": {"name": "Done"}}]}
        if key:
            i = self.issues[key]
            return 200, {"key": key, "fields": {"project": {"key": i["project"]}, "status": {"name": self.status},
                                                "summary": "RE-xx something",
                                                "attachment": [{"filename": f} for f in self.attachments.get(key, [])],
                                                "assignee": {"accountId": i["assignee"], "displayName": i["name"]}}}
        return 404, {}

    def writes(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


def jira(fake, cfg=None, apply=True, tmp_path=None) -> js.Jira:
    j = js.Jira(cfg or config(), apply=apply, transport=fake, email="allen@example.com", token="t")
    if tmp_path is not None:
        j.audit_path = tmp_path / "audit.jsonl"
    return j


def sync(fake, tmp_path, **kw):
    cfg = kw.pop("cfg", None)
    apply = kw.pop("apply", True)
    return js.run_sync(jira(fake, cfg=cfg, apply=apply, tmp_path=tmp_path), today="17 Oct 2026", **kw)


# --- configuration ------------------------------------------------------------------------------


@pytest.mark.parametrize("change, message", [
    ({"base_url": "https://evil.example.com"}, "base_url"),
    ({"project_key": ""}, "project_key"),
    ({"allen_account_id": ""}, "allen_account_id"),
    ({"issues": {"OTHER-5": ["ENG-12"]}}, "not an issue of project SRE"),
    ({"issues": {"SRE-1": ["SOMETHING"]}}, "ENG ids"),
    ({"transitions": {"Built": "Closed"}}, "jira_status_order"),
    ({"transitions": {"Shipped": "Done"}}, "not an engine status"),
    ({"notes": {"SRE-9": "x"}}, "not one of the"),
    ({"max_writes_per_run": 500}, "max_writes_per_run"),
])
def test_a_bad_configuration_refuses_to_run(change, message) -> None:
    with pytest.raises(js.GuardError, match=message):
        config(**change)


def test_a_blank_settings_file_refuses_and_check_alone_runs_without_an_account(tmp_path) -> None:
    blank = tmp_path / "jira_sync.toml"
    blank.write_text('base_url = ""\nproject_key = ""\nallen_account_id = ""\n', encoding="utf-8")
    with pytest.raises(js.GuardError):
        js.Config.load(blank)
    no_account = tmp_path / "no_account.toml"
    no_account.write_text('base_url = "https://mysoco.atlassian.net"\nproject_key = "SRE"\nallen_account_id = ""\n',
                          encoding="utf-8")
    with pytest.raises(js.GuardError, match="allen_account_id"):
        js.Config.load(no_account)
    assert js.Config.load(no_account, need_account=False).project_key == "SRE"  # `check` only


def test_the_shipped_settings_are_valid_and_only_name_sre_issues() -> None:
    cfg = js.Config.load()
    assert cfg.project_key == "SRE" and all(k.startswith("SRE-") for k in cfg.issues)
    owners = js.build_list_owners()
    assert all(owners[e] == "Allen" for engs in cfg.issues.values() for e in engs)


# --- the request guard --------------------------------------------------------------------------


@pytest.mark.parametrize("method, path", [
    ("DELETE", "/rest/api/3/issue/SRE-1"),
    ("PUT", "/rest/api/3/issue/SRE-1"),  # editing fields
    ("POST", "/rest/api/3/issue"),  # creating an issue
    ("PUT", "/rest/api/3/issue/SRE-1/assignee"),
    ("POST", "/rest/api/3/issue/OTHER-1/comment"),  # another project
    ("GET", "/rest/api/3/issue/OTHER-1"),
    ("POST", "/rest/api/3/issueLink"),
    ("POST", "/rest/api/3/issue/bulk"),
    ("GET", "/rest/api/3/project/OTHER"),
    ("PUT", "/rest/api/3/issue/SRE-1/comment/5"),  # editing someone's comment
    ("DELETE", "/rest/api/3/issue/SRE-1/comment/5"),
])
def test_only_the_listed_requests_are_ever_sent(method, path) -> None:
    fake = FakeJira()
    with pytest.raises(js.GuardError, match="not an allowed request"):
        jira(fake).request(method, path)
    assert fake.calls == []


def test_a_search_must_stay_in_the_project() -> None:
    fake = FakeJira()
    with pytest.raises(js.GuardError, match="limited to the configured project"):
        jira(fake).request("GET", "/rest/api/3/search/jql", {"jql": "assignee = currentUser()"})
    with pytest.raises(js.GuardError, match="limited to the configured project"):
        jira(fake).request("GET", "/rest/api/3/search/jql", {"jql": 'project = "OTHER" AND assignee = x'})
    assert fake.calls == []


def test_no_write_in_a_dry_run(tmp_path) -> None:
    fake = FakeJira()
    j = jira(fake, apply=False, tmp_path=tmp_path)
    j.verify_issue("SRE-1")
    with pytest.raises(js.GuardError, match="dry run"):
        j.request("POST", "/rest/api/3/issue/SRE-1/comment", payload={})
    assert fake.writes() == []


def test_no_write_to_an_issue_not_verified_in_this_run() -> None:
    fake = FakeJira()
    with pytest.raises(js.GuardError, match="not verified"):
        jira(fake).request("POST", "/rest/api/3/issue/SRE-1/comment", payload={})
    assert fake.writes() == []


def test_the_token_must_be_allens(tmp_path) -> None:
    fake = FakeJira(me=OTHER)
    with pytest.raises(js.GuardError, match="token belongs to"):
        sync(fake, tmp_path)
    assert fake.writes() == []


def test_an_issue_assigned_to_someone_else_is_skipped(tmp_path) -> None:
    fake = FakeJira(issues={"SRE-1": {"project": "SRE", "assignee": OTHER, "name": "Someone"},
                            "SRE-2": {"project": "SRE", "assignee": ALLEN, "name": "Allen Matthew"}})
    report = sync(fake, tmp_path)
    assert any(line.startswith("SKIP skip SRE-1: assigned to") for line in report)
    assert all("SRE-1/" not in p for _, p in fake.writes())
    assert any("SRE-2/" in p for _, p in fake.writes())
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert any(a["action"] == "skipped" and a["issue"] == "SRE-1" for a in audit)


def test_an_issue_moved_to_another_project_is_skipped(tmp_path) -> None:
    fake = FakeJira(issues={"SRE-1": {"project": "OTHER", "assignee": ALLEN, "name": "Allen Matthew"},
                            "SRE-2": {"project": "SRE", "assignee": ALLEN, "name": "Allen Matthew"}})
    sync(fake, tmp_path)
    assert all("SRE-1/" not in p for _, p in fake.writes())


def test_an_issue_with_a_task_that_is_not_allens_is_refused(tmp_path, monkeypatch) -> None:
    owners = js.build_list_owners()
    monkeypatch.setattr(js, "build_list_owners", lambda: {**owners, "ENG-15": "Aravinth"})
    fake = FakeJira()
    report = sync(fake, tmp_path)
    assert any("REFUSED SRE-2: ENG-15's Build List owner" in line for line in report)
    assert all("SRE-2/" not in p for _, p in fake.writes())  # the whole issue, not just that task


# --- what it writes -----------------------------------------------------------------------------


def test_a_comment_then_a_forward_move_and_nothing_else(tmp_path, monkeypatch) -> None:
    tasks = js.read_tasks()
    for eng in ("ENG-12", "ENG-13", "ENG-15"):  # fixed here, whatever the vault says later
        tasks[eng] = js.Task(eng, "Built", "Allen", tasks[eng].name)
    monkeypatch.setattr(js, "read_tasks", lambda: tasks)
    fake = FakeJira()
    report = sync(fake, tmp_path)
    assert set(fake.writes()) == {("POST", "/rest/api/3/issue/SRE-1/comment"), ("POST", "/rest/api/3/issue/SRE-1/transitions"),
                                  ("POST", "/rest/api/3/issue/SRE-2/comment"), ("POST", "/rest/api/3/issue/SRE-2/transitions")}
    body = next(b for m, p, b in fake.calls if p.endswith("SRE-2/comment") and m == "POST")
    text = json.dumps(body)
    assert "Status update, 17 Oct 2026: Built." in text and "ENG-13" in text and "ENG-15" in text
    assert "least advanced" in text and "Sync ref: SRE-2/" in text and "Claude" not in text
    assert any("moved 'To Do' -> 'In Progress'" in line for line in report)


def test_an_issue_takes_its_least_advanced_tasks_status(tmp_path, monkeypatch) -> None:
    tasks = js.read_tasks()
    tasks["ENG-15"] = js.Task("ENG-15", "In progress", "Allen", "Merge")
    monkeypatch.setattr(js, "read_tasks", lambda: tasks)
    fake = FakeJira()
    report = sync(fake, tmp_path, apply=False)
    assert any(line.startswith("SRE-2 (ENG-13+ENG-15)") and "(In progress)" in line for line in report)


def test_a_passed_task_moves_to_done(tmp_path, monkeypatch) -> None:
    tasks = js.read_tasks()
    tasks["ENG-12"] = js.Task("ENG-12", "Passed", "Allen", "Candidate sources")
    monkeypatch.setattr(js, "read_tasks", lambda: tasks)
    report = sync(FakeJira(), tmp_path)
    assert any("SRE-1" in line for line in report) and any("moved 'To Do' -> 'Done'" in line for line in report)


def test_a_task_not_started_is_left_alone(tmp_path, monkeypatch) -> None:
    tasks = js.read_tasks()
    tasks["ENG-21"] = js.Task("ENG-21", "To build", "Allen", "Fraud rules")  # not started, whatever the vault says later
    monkeypatch.setattr(js, "read_tasks", lambda: tasks)
    fake = FakeJira()
    report = sync(fake, tmp_path, cfg=config(issues={"SRE-1": ["ENG-21"]}))
    assert fake.writes() == [] and any("not started, nothing to report" in line for line in report)


def test_a_note_is_added_to_the_issues_comment(tmp_path) -> None:
    fake = FakeJira()
    sync(fake, tmp_path, cfg=config(notes={"SRE-1": "Wave 1A scope: reason_code is null."}))
    body = next(b for m, p, b in fake.calls if p.endswith("SRE-1/comment") and m == "POST")
    assert "Wave 1A scope: reason_code is null." in json.dumps(body)


def test_the_same_update_is_never_posted_twice(tmp_path) -> None:
    tasks = js.read_tasks()
    ref = js.fingerprint("SRE-1", [tasks["ENG-12"]])
    fake = FakeJira(comments={"SRE-1": {"comments": [{"body": {"content": [{"text": f"Sync ref: SRE-1/{ref}"}]}}]}},
                    status="In Progress")
    report = sync(fake, tmp_path)
    assert any(line.startswith("SRE-1 (ENG-12)") and "up to date" in line for line in report)
    assert ("POST", "/rest/api/3/issue/SRE-1/comment") not in fake.writes()


def test_never_moves_an_issue_backwards(tmp_path) -> None:
    fake = FakeJira(status="Done")
    report = sync(fake, tmp_path)
    assert not any(p.endswith("/transitions") for m, p in fake.writes())
    assert any("only forward" in line for line in report)


def test_a_run_stops_at_max_writes(tmp_path) -> None:
    fake = FakeJira()
    with pytest.raises(js.GuardError, match="max_writes_per_run"):
        sync(fake, tmp_path, cfg=config(max_writes_per_run=1))
    assert len(fake.writes()) == 1


def test_a_dry_run_reports_and_writes_nothing(tmp_path) -> None:
    fake = FakeJira()
    report = sync(fake, tmp_path, apply=False, show=True)
    assert fake.writes() == [] and any("would comment" in line for line in report)
    assert any(line.strip().startswith("| Status update") for line in report)  # the comment, in full


# --- matching differently worded tasks ----------------------------------------------------------


TASKS = {
    "ENG-13": "M2 retrieval Retrieval method one quotas Build a pool of 300 candidates interest follows trending popular round-robin",
    "ENG-14": "M2 retrieval Retrieval method two similar posts computed nightly vector cosine profile engaged posts",
    "ENG-16": "M8 promoter score Promoter score both methods reach content quality consistency net commerce conversion",
}


def test_a_reworded_issue_matches_its_task() -> None:
    issues = [("SRE-7", "Candidate pool with quotas from interests, follows, trending and popular posts\n"),
              ("SRE-8", "Nightly job: similar posts per user using cosine on post vectors\n"),
              ("SRE-9", "Creator/promoter scoring (reach, quality, commerce) - two methods\n")]
    got = {m.issue: (m.eng, m.confident) for m in js.match_issues(issues, TASKS)}
    assert got == {"SRE-7": ("ENG-13", True), "SRE-8": ("ENG-14", True), "SRE-9": ("ENG-16", True)}


def test_an_eng_id_in_the_issue_wins() -> None:
    [m] = js.match_issues([("SRE-3", "ENG 14 - follow-ups\nsome text about quotas")], TASKS)
    assert (m.eng, m.score, m.confident) == ("ENG-14", 1.0, True)


def test_an_unclear_issue_is_not_confident() -> None:
    [m] = js.match_issues([("SRE-4", "Weekly sync meeting notes\n")], TASKS)
    assert not m.confident


def test_approve_copies_only_confident_matches_under_issues(tmp_path) -> None:
    settings = tmp_path / "jira_sync.toml"
    settings.write_text('base_url = "https://mysoco.atlassian.net"\nproject_key = "SRE"\nallen_account_id = "acc-allen"\n'
                        'jira_status_order = ["To Do", "Done"]\n[transitions]\n[issues]\n"SRE-1" = ["ENG-12"]\n'
                        '[notes]\n"SRE-1" = "a note"\n', encoding="utf-8")
    proposals = tmp_path / "proposed.json"
    proposals.write_text(json.dumps([
        {"issue": "SRE-7", "eng": "ENG-13", "confident": True},
        {"issue": "SRE-4", "eng": "ENG-14", "confident": False},
        {"issue": "SRE-1", "eng": "ENG-16", "confident": True},  # already mapped: left as it is
    ]), encoding="utf-8")
    js.approve(js.Config.load(settings), settings, proposals)
    cfg = js.Config.load(settings)
    assert cfg.issues == {"SRE-1": ["ENG-12"], "SRE-7": ["ENG-13"]} and cfg.notes == {"SRE-1": "a note"}


# --- proofs attached ----------------------------------------------------------------------------


@pytest.fixture
def proofs(tmp_path, monkeypatch):
    """A pretend Test Output/ with ENG-12 (all passed) and ENG-15 (one check not passed)."""
    folder = tmp_path / "Test Output"
    (folder / "M2").mkdir(parents=True)
    for eng, body in (("ENG-12", "\n## PASS  12.1 a\n\n## PASS  12.2 b\n"),
                      ("ENG-15", "\n## PASS  14.1 a\n\n## FAIL  14.2 on a database\n")):
        (folder / "M2" / f"{eng}.md").write_text(f"# {eng}: check output\n- **Run:** 2026-10-17 14:46 IST\n{body}",
                                                 encoding="utf-8")
        (folder / "M2" / f"{eng}.pdf").write_bytes(b"%PDF-1.4 proof of " + eng.encode())
    monkeypatch.setattr(js, "PROOFS", folder)
    return folder


def test_each_tasks_proof_is_attached_and_named_in_the_comment(tmp_path, proofs) -> None:
    fake = FakeJira()
    report = sync(fake, tmp_path, cfg=config(attach_proofs=True))
    uploads = [(p, b) for m, p, b in fake.calls if p.endswith("/attachments")]
    assert [p for p, _ in uploads] == ["/rest/api/3/issue/SRE-1/attachments", "/rest/api/3/issue/SRE-2/attachments"]
    assert b'filename="ENG-12_check_output_2026-10-17.pdf"' in uploads[0][1] and b"%PDF-1.4 proof of ENG-12" in uploads[0][1]
    assert all(h.get("X-Atlassian-Token") == "no-check" for h in fake.headers if "multipart" in h.get("Content-Type", ""))
    comment = json.dumps(next(b for m, p, b in fake.calls if p.endswith("SRE-1/comment") and m == "POST"))
    assert "Proof attached: ENG-12_check_output_2026-10-17.pdf (2 checks passed)." in comment
    sre2 = json.dumps(next(b for m, p, b in fake.calls if p.endswith("SRE-2/comment") and m == "POST"))
    assert "ENG-15_check_output_2026-10-17.pdf (1 checks passed, 1 not passed: 14.2 on a database" in sre2
    assert any("attached ENG-12_check_output_2026-10-17.pdf" in line for line in report)


def test_a_proof_already_on_the_issue_is_not_attached_again(tmp_path, proofs) -> None:
    fake = FakeJira(attachments={"SRE-1": ["ENG-12_check_output_2026-10-17.pdf"]})
    sync(fake, tmp_path, cfg=config(attach_proofs=True))
    assert ("POST", "/rest/api/3/issue/SRE-1/attachments") not in fake.writes()


def test_an_attachment_cannot_be_sent_without_attach() -> None:
    fake = FakeJira()
    j = jira(fake)
    j.verify_issue("SRE-1")
    with pytest.raises(js.GuardError, match="only through attach"):
        j.request("POST", "/rest/api/3/issue/SRE-1/attachments", payload={})
    assert fake.writes() == []


def test_only_a_covered_tasks_pdf_from_test_output_is_attached(tmp_path, proofs, monkeypatch) -> None:
    fake = FakeJira()
    j = jira(fake)
    j.verify_issue("SRE-1")
    proof = js.find_proof("ENG-15")
    with pytest.raises(js.GuardError, match="not the proof of a task"):
        j.attach("SRE-1", proof, ["ENG-12"])  # SRE-1 covers ENG-12 only
    outside = tmp_path / "ENG-12.pdf"
    outside.write_bytes(b"%PDF elsewhere")
    with pytest.raises(js.GuardError, match="not a PDF in Test Output"):
        j.attach("SRE-1", js.Proof("ENG-12", outside, "2026-10-17", 1, []), ["ENG-12"])
    text = proofs / "M2" / "ENG-12.md"
    with pytest.raises(js.GuardError, match="not a PDF in Test Output"):
        j.attach("SRE-1", js.Proof("ENG-12", text, "2026-10-17", 1, []), ["ENG-12"])
    monkeypatch.setattr(js, "MAX_ATTACHMENT_BYTES", 5)
    with pytest.raises(js.GuardError, match="over 10 MB"):
        j.attach("SRE-1", js.find_proof("ENG-12"), ["ENG-12"])
    assert fake.writes() == []


def test_an_unverified_issue_gets_no_attachment(proofs) -> None:
    fake = FakeJira()
    with pytest.raises(js.GuardError, match="not verified"):
        jira(fake).attach("SRE-1", js.find_proof("ENG-12"), ["ENG-12"])
    assert fake.writes() == []


def test_the_proofs_folder_setting_is_guarded(tmp_path) -> None:
    with pytest.raises(js.GuardError, match="proofs_folder"):
        config(proofs_folder="../elsewhere")
    with pytest.raises(js.GuardError, match="proofs_folder"):
        config(proofs_folder="Documents")
    assert js.proofs_root(config(proofs_folder="Test Output (test server)")) == js.ROOT / "Test Output (test server)"

