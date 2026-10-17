"""Keep Allen Matthew's Jira issues up to date from the repo, and touch nothing else.

    python scripts/jira_sync.py check              # connection, who the token is, the project (read only)
    python scripts/jira_sync.py discover           # match Allen's issues to the Build List tasks (read only)
    python scripts/jira_sync.py approve            # copy the confident matches into settings/jira_sync.toml
    python scripts/jira_sync.py plan               # what sync would do (read only; the default)
    python scripts/jira_sync.py sync --apply       # do it: comments and forward transitions only
    python scripts/jira_sync.py sync --apply --every 30    # keep doing it every 30 minutes

Matching (Allen, 17 Oct 2026): the Jira tasks are worded differently from the
Build List, but describe the same work. `discover` reads each of Allen's issues in
the project (summary and description) and scores it against every task of Allen's
in the Build List (its name, what to build, its model) and the vault note's title:
an ENG id written in the issue wins outright; otherwise a word-overlap score
(TF-IDF cosine, 0 to 1). A match is confident when its score is at least 0.35 and
clearly ahead of the next task (by 0.08). One task may have several issues.

Where the updates come from: each task note in obsidian/Tasks/ (frontmatter task,
status, owner; the "In one line" and the status callout) and the Build List v1.4
(the owner column). The engine's own status words (To build, In progress, Built,
Waiting, Passed) are what get reported.

What it may do, and nothing else:
  - read: the token's own user, one issue, its comments, its transitions, a search
    limited to the project and Allen as assignee;
  - add one comment to an issue when that task's status or summary has changed;
  - move an issue forward to the Jira status configured for the task's status.
It never creates, edits, assigns, deletes, links or bulk-changes anything, never
touches another project, and never touches an issue not assigned to Allen.

Guardrails (each one stops the run, or skips the issue, before any write):
  1. Dry run unless --apply.
  2. One project only (settings/jira_sync.toml project_key); every issue key must
     start with it, and the issue's own project must be it.
  3. Only issues listed in [issues] (ENG id -> issue key or keys). `discover` only
     proposes; `approve` writes only confident, one-to-one matches, after showing
     them; the rest Allen copies by hand. Nothing is found and changed in one step.
  4. The task must be Allen's twice over: owner Allen in the Build List, and owner
     Allen in the vault note.
  5. The issue is re-read just before each write: its assignee must be Allen's
     accountId (and display name), or it is skipped.
  6. The API token must belong to Allen (GET /myself accountId = allen_account_id),
     so every change is made as Allen.
  7. One function sends every request, and it allows only the reads above and two
     writes (POST comment, POST transition) on an issue verified in this run.
  8. Transitions only forward along jira_status_order, never back.
  9. At most max_writes_per_run writes per run; a failed write stops the run.
 10. Every write, and every refusal, is appended to Tracing/jira/audit.jsonl.
 11. A comment carries a marker; the same update is never posted twice.

Credentials: JIRA_EMAIL and JIRA_API_TOKEN from the environment (.env). They are
never printed or logged.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "settings" / "jira_sync.toml"
TASKS = ROOT / "obsidian" / "Tasks"
PACK = ROOT / "Tracing" / "pack_text"
OUT = ROOT / "Tracing" / "jira"
OWNER = "Allen"
MARKER = "reco-sync"


class GuardError(RuntimeError):
    """A guardrail refused the action. The run stops or the issue is skipped."""


# --- configuration --------------------------------------------------------------------------------


@dataclass
class Config:
    base_url: str
    project_key: str
    allen_account_id: str
    allen_display_name: str
    issues: dict[str, list[str]]
    transitions: dict[str, str]
    jira_status_order: list[str]
    max_writes_per_run: int = 20

    @classmethod
    def load(cls, path: Path = CONFIG, need_account: bool = True) -> Config:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        cfg = cls(
            base_url=str(data.get("base_url", "")).rstrip("/"),
            project_key=str(data.get("project_key", "")).strip(),
            allen_account_id=str(data.get("allen_account_id", "")).strip(),
            allen_display_name=str(data.get("allen_display_name", "Allen Matthew")).strip(),
            issues={str(k).upper(): [str(x).strip().upper() for x in (v if isinstance(v, list) else [v])]
                    for k, v in (data.get("issues") or {}).items()},
            transitions={str(k): str(v) for k, v in (data.get("transitions") or {}).items()},
            jira_status_order=[str(s) for s in data.get("jira_status_order") or []],
            max_writes_per_run=int(data.get("max_writes_per_run", 20)),
        )
        cfg.validate(need_account)
        return cfg

    def validate(self, need_account: bool = True) -> None:
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+\.atlassian\.net", self.base_url):
            raise GuardError("base_url must be https://<site>.atlassian.net (settings/jira_sync.toml)")
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", self.project_key):
            raise GuardError("project_key must be one Jira project key, e.g. SOCO (settings/jira_sync.toml)")
        if need_account and not self.allen_account_id:
            raise GuardError("allen_account_id is empty: run `check` and copy your accountId into settings/jira_sync.toml")
        if not 1 <= self.max_writes_per_run <= 50:
            raise GuardError("max_writes_per_run must be 1 to 50")
        keys = [key for keys in self.issues.values() for key in keys]
        for eng, mapped in self.issues.items():
            if not re.fullmatch(r"ENG-\d{2}", eng):
                raise GuardError(f"[issues] {eng!r} is not an ENG id")
            for key in mapped:
                if not re.fullmatch(rf"{self.project_key}-\d+", key):
                    raise GuardError(f"[issues] {eng} -> {key}: not an issue of project {self.project_key}")
        if len(set(keys)) != len(keys):
            raise GuardError("[issues] maps two tasks to the same issue")
        for status, target in self.transitions.items():
            if target not in self.jira_status_order:
                raise GuardError(f"[transitions] {status} -> {target!r}: not in jira_status_order")


# --- the source of truth: the vault and the Build List -------------------------------------------


@dataclass
class Task:
    eng: str
    status: str
    owner: str
    title: str
    one_line: str
    status_line: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.status}\n{self.status_line}\n{self.one_line}".encode()).hexdigest()[:12]


def build_list_owners(pack: Path = PACK) -> dict[str, str]:
    """ENG id -> owner, from the Build List v1.4 text (the pack is final, read only)."""
    build_list = sorted(pack.glob("SOCO-REC_Wave1A_Build_List_*.txt"))[-1]
    owners = {}
    for line in build_list.read_text(encoding="utf-8").splitlines():
        cells = line.split(" | ")
        if len(cells) > 3 and re.fullmatch(r"ENG-\d{2}", cells[0]):
            owners[cells[0]] = cells[2].strip()
    return owners


def build_list_texts(pack: Path = PACK) -> dict[str, str]:
    """Allen's ENG ids -> the words that describe the task: its model, name and what to build."""
    build_list = sorted(pack.glob("SOCO-REC_Wave1A_Build_List_*.txt"))[-1]
    texts = {}
    for line in build_list.read_text(encoding="utf-8").splitlines():
        cells = line.split(" | ")
        if len(cells) > 7 and re.fullmatch(r"ENG-\d{2}", cells[0]) and cells[2].strip() == OWNER:
            texts.setdefault(cells[0], " ".join(cells[3:7]))
    return texts


def read_tasks(folder: Path = TASKS) -> dict[str, Task]:
    tasks = {}
    for note in sorted(folder.glob("ENG-*.md")):
        text = note.read_text(encoding="utf-8")
        front = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if not front:
            continue
        meta = dict(re.findall(r"^(\w+):\s*(.+?)\s*$", front.group(1), re.M))
        eng = meta.get("task", "").strip()
        if not re.fullmatch(r"ENG-\d{2}", eng):
            continue
        title = (re.search(r"^# (.+)$", text, re.M) or [None, note.stem])[1]
        one = re.search(r"^\*\*In one line:\*\*\s*(.+)$", text, re.M)
        callout = re.search(r"^> \[!note\] Status: (.+)$", text, re.M)
        tasks[eng] = Task(eng=eng, status=meta.get("status", "").strip(), owner=meta.get("owner", "").strip(),
                          title=title.strip(), one_line=one.group(1).strip() if one else "",
                          status_line=re.sub(r"\*\*", "", callout.group(1)).strip() if callout else "")
    return tasks


# --- the only way out: one guarded request function ----------------------------------------------

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else None
        except ValueError:
            return exc.code, {"error": raw[:300].decode("utf-8", "replace")}


@dataclass
class Jira:
    cfg: Config
    apply: bool
    transport: Transport = urllib_transport
    email: str = field(default_factory=lambda: os.environ.get("JIRA_EMAIL", ""))
    token: str = field(default_factory=lambda: os.environ.get("JIRA_API_TOKEN", ""), repr=False)
    verified: set[str] = field(default_factory=set)  # issue keys checked in this run, writable
    writes: int = 0
    audit_path: Path = OUT / "audit.jsonl"

    def _allowed(self, method: str, path: str) -> str | None:
        """The issue key the request is about, or None for a non-issue read. Raises
        GuardError for anything not on the list."""
        key = rf"{re.escape(self.cfg.project_key)}-\d+"
        reads = [r"/rest/api/3/myself", r"/rest/api/3/search/jql", r"/rest/api/3/project/" + re.escape(self.cfg.project_key)]
        if method == "GET" and any(re.fullmatch(p, path) for p in reads):
            return None
        m = re.fullmatch(rf"/rest/api/3/issue/({key})(/comment|/transitions)?", path)
        if m and method == "GET":
            return m.group(1)
        if m and method == "POST" and m.group(2) in ("/comment", "/transitions"):
            return m.group(1)
        raise GuardError(f"refused: {method} {path} is not an allowed request")

    def request(self, method: str, path: str, query: dict[str, str] | None = None, payload: Any = None) -> Any:
        issue = self._allowed(method, path)
        if method == "POST":
            if not self.apply:
                raise GuardError("refused: a write in a dry run")
            if issue not in self.verified:
                raise GuardError(f"refused: {issue} was not verified as Allen's in this run")
            if self.writes >= self.cfg.max_writes_per_run:
                raise GuardError(f"refused: max_writes_per_run ({self.cfg.max_writes_per_run}) reached")
        if not self.email or not self.token:
            raise GuardError("JIRA_EMAIL and JIRA_API_TOKEN must be set (in .env)")
        url = self.cfg.base_url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        auth = base64.b64encode(f"{self.email}:{self.token}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "Accept": "application/json", "Content-Type": "application/json"}
        body = json.dumps(payload).encode() if payload is not None else None
        status, data = self.transport(method, url, headers, body)
        if method == "POST":
            self.writes += 1
        if status >= 400:
            raise RuntimeError(f"Jira answered {status} to {method} {path}: {json.dumps(data)[:300]}")
        return data

    def audit(self, **entry: Any) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "apply": self.apply, **entry}
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # --- checks ---------------------------------------------------------------------------

    def check_identity(self) -> dict[str, Any]:
        me = self.request("GET", "/rest/api/3/myself")
        if me.get("accountId") != self.cfg.allen_account_id:
            raise GuardError(f"refused: the API token belongs to {me.get('displayName')!r}, not {self.cfg.allen_display_name!r}")
        return me

    def verify_issue(self, key: str) -> dict[str, Any]:
        """Re-read the issue now; it becomes writable only if it is Allen's, in the project."""
        self.verified.discard(key)
        issue = self.request("GET", f"/rest/api/3/issue/{key}", {"fields": "project,assignee,status,summary"})
        fields = issue.get("fields") or {}
        project = (fields.get("project") or {}).get("key")
        assignee = fields.get("assignee") or {}
        if project != self.cfg.project_key or not key.startswith(self.cfg.project_key + "-"):
            raise GuardError(f"skip {key}: project {project!r}, not {self.cfg.project_key}")
        if assignee.get("accountId") != self.cfg.allen_account_id:
            raise GuardError(f"skip {key}: assigned to {assignee.get('displayName')!r}, not {self.cfg.allen_display_name}")
        if assignee.get("displayName") and assignee["displayName"] != self.cfg.allen_display_name:
            raise GuardError(f"skip {key}: assignee name {assignee['displayName']!r} does not match")
        self.verified.add(key)
        return issue


# --- what to do ---------------------------------------------------------------------------------


def comment_body(task: Task, commit: str) -> dict[str, Any]:
    """Atlassian document format, plain paragraphs, with the marker that stops a repeat."""
    lines = [f"SOCO engine update: {task.eng} is {task.status}.",
             task.status_line, task.one_line,
             f"From the repo (branch work, commit {commit}); details in docs/engineering/{task.eng}.md.",
             f"[{MARKER} {task.eng} {task.fingerprint}]"]
    return {"body": {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]} for line in lines if line]}}


def already_posted(comments: dict[str, Any], task: Task) -> bool:
    marker = f"[{MARKER} {task.eng} {task.fingerprint}]"
    return marker in json.dumps(comments or {}, ensure_ascii=False)


def eligible_tasks(cfg: Config, tasks: dict[str, Task], owners: dict[str, str]) -> tuple[list[tuple[Task, str]], list[str]]:
    """(task, issue key) pairs that pass guardrails 3 and 4, and why the others don't."""
    ok, refused = [], []
    for eng, keys in sorted(cfg.issues.items()):
        task = tasks.get(eng)
        if task is None:
            refused.append(f"{eng}: no task note in obsidian/Tasks")
        elif owners.get(eng) != OWNER:
            refused.append(f"{eng}: Build List owner is {owners.get(eng)!r}, not {OWNER}")
        elif task.owner != OWNER:
            refused.append(f"{eng}: the vault note's owner is {task.owner!r}, not {OWNER}")
        else:
            ok.extend((task, key) for key in keys)
    return ok, refused


def forward(order: list[str], current: str, target: str) -> bool:
    if current not in order or target not in order:
        return False
    return order.index(target) > order.index(current)


def run_sync(jira: Jira, commit: str) -> list[str]:
    cfg = jira.cfg
    report: list[str] = []
    me = jira.check_identity()
    report.append(f"token is {me.get('displayName')} ({'apply' if jira.apply else 'dry run'})")
    pairs, refused = eligible_tasks(cfg, read_tasks(), build_list_owners())
    for reason in refused:
        report.append(f"REFUSED {reason}")
        jira.audit(action="refused", reason=reason)
    for task, key in pairs:
        try:
            issue = jira.verify_issue(key)
        except GuardError as exc:
            report.append(f"SKIP {exc}")
            jira.audit(action="skipped", issue=key, eng=task.eng, reason=str(exc))
            continue
        status_now = ((issue.get("fields") or {}).get("status") or {}).get("name", "")
        comments = jira.request("GET", f"/rest/api/3/issue/{key}/comment", {"maxResults": "100", "orderBy": "-created"})
        if already_posted(comments, task):
            report.append(f"{key} ({task.eng}): up to date ({task.status})")
        elif jira.apply:
            jira.request("POST", f"/rest/api/3/issue/{key}/comment", payload=comment_body(task, commit))
            jira.audit(action="comment", issue=key, eng=task.eng, status=task.status, fingerprint=task.fingerprint)
            report.append(f"{key} ({task.eng}): commented ({task.status})")
        else:
            report.append(f"{key} ({task.eng}): would comment ({task.status})")
        target = cfg.transitions.get(task.status)
        if target and target != status_now:
            if not forward(cfg.jira_status_order, status_now, target):
                report.append(f"{key}: not moving {status_now!r} -> {target!r} (only forward)")
                continue
            options = jira.request("GET", f"/rest/api/3/issue/{key}/transitions").get("transitions", [])
            move = next((t for t in options if (t.get("to") or {}).get("name") == target), None)
            if move is None:
                report.append(f"{key}: no transition to {target!r} from {status_now!r} in this workflow")
            elif jira.apply:
                jira.request("POST", f"/rest/api/3/issue/{key}/transitions", payload={"transition": {"id": move["id"]}})
                jira.audit(action="transition", issue=key, eng=task.eng, from_status=status_now, to_status=target)
                report.append(f"{key}: moved {status_now!r} -> {target!r}")
            else:
                report.append(f"{key}: would move {status_now!r} -> {target!r}")
    return report


_STOP = set("""a an and are as at be by for from has have in into is it its of on or that the this to
was were will with not no all each any one two three per than then so do done we our your you their they
build make use used using via also must only after before both every out up new task item engine soco""".split())
CONFIDENT, MARGIN = 0.35, 0.08


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 2]


def adf_text(node: Any) -> str:
    """Plain text of an Atlassian document (a Jira description)."""
    if isinstance(node, dict):
        return " ".join([node.get("text", "")] + [adf_text(c) for c in node.get("content") or []])
    if isinstance(node, list):
        return " ".join(adf_text(c) for c in node)
    return node if isinstance(node, str) else ""


@dataclass
class Match:
    issue: str
    summary: str
    eng: str | None
    score: float
    runner_up: tuple[str, float] | None
    confident: bool
    reason: str


def match_issues(issues: list[tuple[str, str]], tasks: dict[str, str]) -> list[Match]:
    """Each (issue key, its text) against Allen's tasks (ENG id -> text): the best task,
    its score (0 to 1), the runner-up, and whether the match is confident."""
    import math
    from collections import Counter

    docs = {eng: Counter(words(text)) for eng, text in tasks.items()}
    issue_docs = {key: Counter(words(text)) for key, text in issues}
    every = list(docs.values()) + list(issue_docs.values())
    df = Counter(w for d in every for w in d)
    idf = {w: math.log((1 + len(every)) / (1 + n)) + 1 for w, n in df.items()}

    def vector(d: Counter) -> dict[str, float]:
        v = {w: (1 + math.log(c)) * idf[w] for w, c in d.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}

    task_vectors = {eng: vector(d) for eng, d in docs.items()}
    out = []
    for key, text in issues:
        named = [e for e in re.findall(r"ENG[-\s]?(\d{2})", text.upper()) if f"ENG-{e}" in tasks]
        summary = text.split("\n", 1)[0][:120]
        if len(set(named)) == 1:
            out.append(Match(key, summary, f"ENG-{named[0]}", 1.0, None, True, "the issue names the ENG id"))
            continue
        iv = vector(issue_docs[key])
        ranked = sorted(((sum(iv.get(w, 0) * x for w, x in tv.items()), eng) for eng, tv in task_vectors.items()),
                        reverse=True)
        (best, eng), runner = ranked[0], (ranked[1] if len(ranked) > 1 else (0.0, None))
        confident = best >= CONFIDENT and best - runner[0] >= MARGIN
        reason = ("confident" if confident else
                  "too weak" if best < CONFIDENT else f"too close to {runner[1]} ({runner[0]:.2f})")
        out.append(Match(key, summary, eng if best > 0 else None, round(best, 3),
                         (runner[1], round(runner[0], 3)) if runner[1] else None, confident, reason))
    return out


def discover(jira: Jira) -> list[str]:
    """Read only: Allen's issues in the project, each matched to a task of Allen's."""
    jira.check_identity()
    jql = f'project = "{jira.cfg.project_key}" AND assignee = "{jira.cfg.allen_account_id}" ORDER BY key'
    found, token = [], None
    while True:
        query = {"jql": jql, "fields": "summary,description,status,assignee", "maxResults": "100"}
        if token:
            query["nextPageToken"] = token
        page = jira.request("GET", "/rest/api/3/search/jql", query)
        found += page.get("issues", [])
        token = page.get("nextPageToken")
        if not token or page.get("isLast", True):
            break
    texts = build_list_texts()
    titles = {eng: t.title for eng, t in read_tasks().items()}
    tasks = {eng: f"{text} {titles.get(eng, '')}" for eng, text in texts.items()}
    issues = [(i["key"], f"{(i.get('fields') or {}).get('summary', '')}\n{adf_text((i.get('fields') or {}).get('description'))}")
              for i in found]
    matches = match_issues(issues, tasks)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "proposed_matches.json").write_text(json.dumps([m.__dict__ for m in matches], indent=2, ensure_ascii=False),
                                              encoding="utf-8")
    lines = [f"{len(found)} issues of {jira.cfg.allen_display_name} in {jira.cfg.project_key}; "
             f"{sum(m.confident for m in matches)} matched confidently. Nothing in Jira was changed.", ""]
    for m in matches:
        mark = "OK " if m.confident else "?? "
        runner = f", next {m.runner_up[0]} {m.runner_up[1]:.2f}" if m.runner_up else ""
        lines.append(f"{mark}{m.issue} -> {m.eng or '-'} ({m.score:.2f}{runner}; {m.reason})  {m.summary}")
    covered = {m.eng for m in matches if m.confident}
    missing = sorted(set(texts) - covered)
    if missing:
        lines += ["", "Tasks of yours with no confident issue: " + ", ".join(missing)]
    lines += ["", f"Saved: {OUT / 'proposed_matches.json'}. Next: `approve` copies the OK lines into "
                  "settings/jira_sync.toml; add the ?? ones by hand if they are right."]
    return lines


def approve(cfg: Config, path: Path = CONFIG, proposals: Path = OUT / "proposed_matches.json") -> list[str]:
    """Copy the confident matches from the last `discover` into [issues], without
    changing any line already there. Touches only the local settings file."""
    matches = json.loads(proposals.read_text(encoding="utf-8"))
    already = {key for keys in cfg.issues.values() for key in keys}
    new: dict[str, list[str]] = {}
    for m in matches:
        if m["confident"] and m["eng"] and m["issue"] not in already:
            new.setdefault(m["eng"], []).append(m["issue"])
    if not new:
        return ["nothing new to approve"]
    text = path.read_text(encoding="utf-8")
    added = []
    for eng, keys in sorted(new.items()):
        merged = sorted(set(cfg.issues.get(eng, [])) | set(keys))
        line = f'"{eng}" = [{", ".join(chr(34) + k + chr(34) for k in merged)}]'
        text, n = re.subn(rf'^"{eng}"\s*=.*$', line, text, flags=re.M)
        if not n:
            text = text.rstrip("\n") + "\n" + line + "\n"
        added.append(line)
    path.write_text(text, encoding="utf-8")
    Config.load(path)  # still valid, or this raises
    return ["added to settings/jira_sync.toml [issues]:"] + added


def current_commit() -> str:
    head = ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            return (ROOT / ".git" / ref[5:]).read_text().strip()[:7]
        return ref[:7]
    except OSError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["check", "discover", "approve", "plan", "sync"], nargs="?", default="plan")
    parser.add_argument("--apply", action="store_true", help="make the changes (sync only); without it nothing is written")
    parser.add_argument("--every", type=int, default=0, metavar="MINUTES", help="repeat sync every N minutes (10 or more)")
    args = parser.parse_args(argv)
    try:
        # `check` is how the accountId is found, so it alone runs without one (it only reads).
        cfg = Config.load(need_account=args.command != "check")
        apply = args.command == "sync" and args.apply
        if args.apply and args.command != "sync":
            raise GuardError("--apply only goes with sync")
        if args.every and (args.command != "sync" or args.every < 10):
            raise GuardError("--every needs sync and at least 10 minutes")
        while True:
            jira = Jira(cfg, apply=apply)
            if args.command == "check":
                me = jira.request("GET", "/rest/api/3/myself")
                if cfg.allen_account_id and me.get("accountId") != cfg.allen_account_id:
                    raise GuardError(f"the API token belongs to {me.get('displayName')!r}, not the configured account")
                project = jira.request("GET", f"/rest/api/3/project/{cfg.project_key}")
                lines = [f"token: {me.get('displayName')} ({me.get('accountId')})",
                         f"project: {project.get('key')} {project.get('name')!r}", "nothing was changed"]
            elif args.command == "discover":
                lines = discover(jira)
            elif args.command == "approve":
                lines = approve(cfg)
            else:
                lines = run_sync(jira, current_commit())
            print("\n".join(lines))
            if not args.every:
                return 0
            time.sleep(args.every * 60)
    except GuardError as exc:
        print(f"STOPPED by a guardrail: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
