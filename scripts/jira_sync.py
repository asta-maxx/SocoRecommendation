"""Keep Allen Matthew's Jira issues up to date from the repo, and touch nothing else.

    python scripts/jira_sync.py check              # connection, who the token is, the project (read only)
    python scripts/jira_sync.py discover           # match Allen's issues to the Build List tasks (read only)
    python scripts/jira_sync.py approve            # copy the confident matches into settings/jira_sync.toml
    python scripts/jira_sync.py plan               # what sync would do, with each comment in full (read only)
    python scripts/jira_sync.py sync --apply       # do it: comments and forward transitions only
    python scripts/jira_sync.py sync --apply --every 30    # keep doing it every 30 minutes

Mapping (settings/jira_sync.toml [issues]): Jira issue key -> the ENG task(s) it
covers. The Jira issues follow the earlier plan (RE-00a to RE-22), worded
differently from the Build List v1.4 (ENG-01 to ENG-30); one issue may cover two
tasks (RE-21 "surface endpoints and latency" is ENG-06 and ENG-20). An issue that
covers several tasks takes the status of the least advanced one.

`discover` proposes matches: an ENG id written in the issue wins outright; otherwise
a word-overlap score (TF-IDF cosine, 0 to 1), confident at 0.35 or more and 0.08
ahead of the next task. `approve` copies only confident ones; the rest Allen
maps by hand (17 Oct 2026: none were confident, the mapping was made by hand).

Where the updates come from: each task note in obsidian/Tasks/ (frontmatter task,
status, owner) and the Build List v1.4 (the task's name and owner). The engine's
status words: To build, In progress, Waiting, Built, Passed.

What it may do, and nothing else:
  - read: the token's own user, the project, one issue, its comments, its
    transitions, a search limited to the project and Allen as assignee;
  - attach each of its tasks' proof (Test Output/<model>/ENG-NN.pdf, the checklist's
    output for that task) once, as ENG-NN_check_output_<run date>.pdf;
  - add one comment to an issue when its tasks' status has changed;
  - move an issue forward to the Jira status configured for that status.
It never creates, edits, assigns, deletes, links or bulk-changes anything, never
touches another project, and never touches an issue not assigned to Allen.

Guardrails (each one stops the run, or skips the issue, before any write):
  1. Dry run unless --apply.
  2. One project only (project_key); every issue key must start with it, and the
     issue's own project must be it.
  3. Only issues listed in [issues], by Allen (or `approve`, confident matches only).
  4. Every task an issue covers must be Allen's twice over: owner Allen in the Build
     List, and owner Allen in the vault note.
  5. The issue is re-read just before each write: its assignee must be Allen's
     accountId (and display name), or it is skipped.
  6. The API token must belong to Allen (GET /myself accountId = allen_account_id).
  7. One function sends every request, and it allows only the reads above and three
     writes (POST attachment, comment, transition) on an issue verified in this run.
     An attachment must be a PDF inside Test Output/, the proof of a task that
     issue covers, under 10 MB, and not already on the issue.
  8. Transitions only forward along jira_status_order, never back.
  9. At most max_writes_per_run writes per run; a failed write stops the run.
 10. Every write, and every refusal, is appended to Tracing/jira/audit.jsonl.
 11. A comment carries a short sync reference; the same update is never posted twice.

Credentials: JIRA_EMAIL and JIRA_API_TOKEN from the environment (.env), never
printed or logged.
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
PROOFS = ROOT / "Test Output"  # settings/jira_sync.toml proofs_folder can name another, e.g. a test-server run
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
OWNER = "Allen"
MARKER = "Sync ref"

#: The engine's statuses, least to most advanced (a task with no vault note is To build).
ENGINE_ORDER = ["To build", "In progress", "Waiting", "Built", "Passed"]
#: How each status reads in a Jira comment.
STATUS_TEXT = {
    "To build": "Not started yet.",
    "In progress": "Work under way.",
    "Waiting": "Built as far as it can be; waiting on the environments it is checked in.",
    "Built": "Development complete and tested on the development environment. It is marked Done once its "
             "acceptance check has run on the test server.",
    "Passed": "Complete: its acceptance check has passed.",
}


class GuardError(RuntimeError):
    """A guardrail refused the action. The run stops or the issue is skipped."""


# --- configuration --------------------------------------------------------------------------------


@dataclass
class Config:
    base_url: str
    project_key: str
    allen_account_id: str
    allen_display_name: str
    issues: dict[str, list[str]]  # Jira issue key -> ENG ids it covers
    transitions: dict[str, str]
    jira_status_order: list[str]
    max_writes_per_run: int = 20
    notes: dict[str, str] = field(default_factory=dict)  # issue key -> one line added to its comment
    attach_proofs: bool = True
    proofs_folder: str = "Test Output"  # under the repo; attachments come only from here

    @classmethod
    def load(cls, path: Path = CONFIG, need_account: bool = True) -> Config:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        cfg = cls(
            base_url=str(data.get("base_url", "")).rstrip("/"),
            project_key=str(data.get("project_key", "")).strip(),
            allen_account_id=str(data.get("allen_account_id", "")).strip(),
            allen_display_name=str(data.get("allen_display_name", "Allen Matthew")).strip(),
            issues={str(k).strip().upper(): [str(x).strip().upper() for x in (v if isinstance(v, list) else [v])]
                    for k, v in (data.get("issues") or {}).items()},
            transitions={str(k): str(v) for k, v in (data.get("transitions") or {}).items()},
            jira_status_order=[str(s) for s in data.get("jira_status_order") or []],
            max_writes_per_run=int(data.get("max_writes_per_run", 20)),
            notes={str(k).strip().upper(): str(v).strip() for k, v in (data.get("notes") or {}).items()},
            attach_proofs=bool(data.get("attach_proofs", True)),
            proofs_folder=str(data.get("proofs_folder", "Test Output")),
        )
        cfg.validate(need_account)
        return cfg

    def validate(self, need_account: bool = True) -> None:
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+\.atlassian\.net", self.base_url):
            raise GuardError("base_url must be https://<site>.atlassian.net (settings/jira_sync.toml)")
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", self.project_key):
            raise GuardError("project_key must be one Jira project key, e.g. SRE (settings/jira_sync.toml)")
        if need_account and not self.allen_account_id:
            raise GuardError("allen_account_id is empty: run `check` and copy your accountId into settings/jira_sync.toml")
        if not 1 <= self.max_writes_per_run <= 50:
            raise GuardError("max_writes_per_run must be 1 to 50")
        for key, engs in self.issues.items():
            if not re.fullmatch(rf"{self.project_key}-\d+", key):
                raise GuardError(f"[issues] {key}: not an issue of project {self.project_key}")
            if not engs or any(not re.fullmatch(r"ENG-\d{2}", e) for e in engs):
                raise GuardError(f"[issues] {key} -> {engs}: each value must be ENG ids")
        for key in self.notes:
            if key not in self.issues:
                raise GuardError(f"[notes] {key}: not one of the [issues]")
        if not self.proofs_folder.startswith("Test Output") or "/" in self.proofs_folder or ".." in self.proofs_folder:
            raise GuardError("proofs_folder must be a folder named 'Test Output...' at the top of the repo")
        for status, target in self.transitions.items():
            if status not in ENGINE_ORDER:
                raise GuardError(f"[transitions] {status!r}: not an engine status ({', '.join(ENGINE_ORDER)})")
            if target not in self.jira_status_order:
                raise GuardError(f"[transitions] {status} -> {target!r}: not in jira_status_order")


# --- the source of truth: the vault and the Build List -------------------------------------------


@dataclass
class Task:
    eng: str
    status: str
    owner: str
    name: str  # the Build List's name for it


def build_list_rows(pack: Path = PACK) -> dict[str, list[str]]:
    """ENG id -> its Build List v1.4 row (the pack is final, read only)."""
    build_list = sorted(pack.glob("SOCO-REC_Wave1A_Build_List_*.txt"))[-1]
    rows = {}
    for line in build_list.read_text(encoding="utf-8").splitlines():
        cells = line.split(" | ")
        if len(cells) > 7 and re.fullmatch(r"ENG-\d{2}", cells[0]):
            rows.setdefault(cells[0], cells)
    return rows


def build_list_owners(pack: Path = PACK) -> dict[str, str]:
    return {eng: cells[2].strip() for eng, cells in build_list_rows(pack).items()}


def build_list_texts(pack: Path = PACK) -> dict[str, str]:
    """Allen's ENG ids -> the words that describe the task: its model, name and what to build."""
    return {eng: " ".join(cells[3:7]) for eng, cells in build_list_rows(pack).items() if cells[2].strip() == OWNER}


def read_tasks(folder: Path = TASKS, pack: Path = PACK) -> dict[str, Task]:
    """Every ENG task of the Build List, with its status from the vault note (none: To build)."""
    rows = build_list_rows(pack)
    notes = {}
    for note in sorted(folder.glob("ENG-*.md")):
        front = re.match(r"---\n(.*?)\n---\n", note.read_text(encoding="utf-8"), re.S)
        if front:
            meta = dict(re.findall(r"^(\w+):\s*(.+?)\s*$", front.group(1), re.M))
            if re.fullmatch(r"ENG-\d{2}", meta.get("task", "")):
                notes[meta["task"]] = meta
    tasks = {}
    for eng, cells in rows.items():
        meta = notes.get(eng, {})
        tasks[eng] = Task(eng=eng, status=meta.get("status", "To build").strip(),
                          owner=meta.get("owner", cells[2]).strip(), name=cells[5].strip())
    return tasks


@dataclass
class Proof:
    eng: str
    pdf: Path
    run_date: str
    passed: int
    failed: list[str]  # the labels of the checks not passed

    @property
    def filename(self) -> str:
        return f"{self.eng}_check_output_{self.run_date}.pdf"

    def summary(self) -> str:
        text = f"{self.filename} ({self.passed} checks passed"
        if self.failed:
            text += f", {len(self.failed)} not passed: " + "; ".join(self.failed) + "; see the note at the top of the file"
        return text + ")"


def proofs_root(cfg: Config | None) -> Path:
    """The folder attachments come from: settings' proofs_folder, else Test Output/."""
    if cfg is None or cfg.proofs_folder == "Test Output":
        return PROOFS
    return ROOT / cfg.proofs_folder


def find_proof(eng: str, folder: Path | None = None) -> Proof | None:
    """The checklist's proof of a task: Test Output/<model>/ENG-NN.pdf and its .md."""
    for pdf in sorted((folder or PROOFS).glob(f"*/{eng}.pdf")):
        md = pdf.with_suffix(".md")
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        run = re.search(r"\*\*Run:\*\* (\d{4}-\d{2}-\d{2})", text)
        return Proof(eng, pdf, run.group(1) if run else "undated", text.count("\n## PASS"),
                     [m.strip() for m in re.findall(r"^## FAIL\s+(.+)$", text, re.M)])
    return None


def least_advanced(tasks: list[Task]) -> str:
    return min((t.status for t in tasks), key=lambda s: ENGINE_ORDER.index(s) if s in ENGINE_ORDER else 0)


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
        m = re.fullmatch(rf"/rest/api/3/issue/({key})(/comment|/transitions|/attachments)?", path)
        if m and method == "GET" and m.group(2) != "/attachments":
            return m.group(1)
        if m and method == "POST" and m.group(2) in ("/comment", "/transitions", "/attachments"):
            return m.group(1)
        raise GuardError(f"refused: {method} {path} is not an allowed request")

    def request(self, method: str, path: str, query: dict[str, str] | None = None, payload: Any = None,
                raw: tuple[bytes, str] | None = None) -> Any:
        issue = self._allowed(method, path)
        if path.endswith("/attachments") and raw is None:
            raise GuardError("refused: an attachment goes only through attach()")
        if method == "GET" and path == "/rest/api/3/search/jql":
            jql = (query or {}).get("jql", "")
            if not re.match(rf'project = "{re.escape(self.cfg.project_key)}" AND ', jql + " "):
                raise GuardError("refused: a search must be limited to the configured project")
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
        if raw is not None:
            body, headers["Content-Type"] = raw
            headers["X-Atlassian-Token"] = "no-check"  # Jira's required header for uploads
        status, data = self.transport(method, url, headers, body)
        if method == "POST":
            self.writes += 1
        if status >= 400:
            raise RuntimeError(f"Jira answered {status} to {method} {path}: {json.dumps(data)[:300]}")
        return data

    def attach(self, key: str, proof: Proof, allowed_engs: list[str]) -> Any:
        """Upload one proof PDF. Only a PDF inside Test Output/, the proof of a task this
        issue covers, under 10 MB; the rest of the guard is request()'s."""
        pdf = proof.pdf.resolve()
        if proofs_root(self.cfg).resolve() not in pdf.parents or pdf.suffix.lower() != ".pdf":
            raise GuardError(f"refused: {pdf} is not a PDF in Test Output/")
        if proof.eng not in allowed_engs or pdf.stem != proof.eng:
            raise GuardError(f"refused: {pdf.name} is not the proof of a task {key} covers")
        data = pdf.read_bytes()
        if not data or len(data) > MAX_ATTACHMENT_BYTES:
            raise GuardError(f"refused: {pdf.name} is empty or over 10 MB")
        boundary = "reco-sync-" + hashlib.sha256(data).hexdigest()[:16]
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{proof.filename}\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        return self.request("POST", f"/rest/api/3/issue/{key}/attachments",
                            raw=(body, f"multipart/form-data; boundary={boundary}"))

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
        issue = self.request("GET", f"/rest/api/3/issue/{key}", {"fields": "project,assignee,status,summary,attachment"})
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


# --- what to write --------------------------------------------------------------------------------


def fingerprint(key: str, tasks: list[Task], note: str = "", proofs: list[Proof] | None = None) -> str:
    text = key + "|" + "|".join(f"{t.eng}:{t.status}" for t in tasks) + "|" + note
    text += "|" + "|".join(p.filename for p in proofs or [])
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def comment_lines(key: str, tasks: list[Task], today: str, note: str = "", proofs: list[Proof] | None = None) -> list[str]:
    """A short, plain status update."""
    status = least_advanced(tasks)
    lines = [f"Status update, {today}: {status}."]
    for t in tasks:
        lines.append(f"{t.eng} {t.name}: {t.status}. {STATUS_TEXT.get(t.status, '')}".strip())
    if len(tasks) > 1:
        lines.append("This issue covers the tasks above; its status follows the least advanced of them.")
    if note:
        lines.append(note)
    for proof in proofs or []:
        lines.append(f"Proof attached: {proof.summary()}.")
    lines.append("Mapped to the Wave 1A Build List v1.4. Details: docs/engineering/" + tasks[0].eng + ".md"
                 + "".join(f", {t.eng}.md" for t in tasks[1:]) + " in the recommendation engine repository.")
    lines.append(f"{MARKER}: {key}/{fingerprint(key, tasks, note, proofs)}")
    return lines


def comment_body(lines: list[str]) -> dict[str, Any]:
    return {"body": {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]} for line in lines]}}


def already_posted(comments: dict[str, Any], key: str, tasks: list[Task], note: str = "",
                   proofs: list[Proof] | None = None) -> bool:
    return f"{MARKER}: {key}/{fingerprint(key, tasks, note, proofs)}" in json.dumps(comments or {}, ensure_ascii=False)


def eligible_issues(cfg: Config, tasks: dict[str, Task], owners: dict[str, str]) -> tuple[list[tuple[str, list[Task]]], list[str]]:
    """(issue key, its tasks) for issues whose every task passes guardrail 4, and why the others don't."""
    ok, refused = [], []
    for key, engs in sorted(cfg.issues.items(), key=lambda kv: int(kv[0].split("-")[1])):
        problem = None
        for eng in engs:
            if eng not in tasks:
                problem = f"{key}: {eng} is not in the Build List"
            elif owners.get(eng) != OWNER:
                problem = f"{key}: {eng}'s Build List owner is {owners.get(eng)!r}, not {OWNER}"
            elif tasks[eng].owner != OWNER:
                problem = f"{key}: {eng}'s vault note owner is {tasks[eng].owner!r}, not {OWNER}"
            if problem:
                break
        if problem:
            refused.append(problem)
        else:
            ok.append((key, [tasks[e] for e in engs]))
    return ok, refused


def forward(order: list[str], current: str, target: str) -> bool:
    if current not in order or target not in order:
        return False
    return order.index(target) > order.index(current)


def run_sync(jira: Jira, today: str | None = None, show: bool = False) -> list[str]:
    cfg = jira.cfg
    today = today or datetime.now(timezone.utc).strftime("%d %b %Y")
    report: list[str] = []
    me = jira.check_identity()
    report.append(f"token is {me.get('displayName')} ({'apply' if jira.apply else 'dry run'}); project {cfg.project_key}")
    pairs, refused = eligible_issues(cfg, read_tasks(), build_list_owners())
    for reason in refused:
        report.append(f"REFUSED {reason}")
        jira.audit(action="refused", reason=reason)
    for key, tasks in pairs:
        engs = "+".join(t.eng for t in tasks)
        try:
            issue = jira.verify_issue(key)
        except GuardError as exc:
            report.append(f"SKIP {exc}")
            jira.audit(action="skipped", issue=key, eng=engs, reason=str(exc))
            continue
        fields = issue.get("fields") or {}
        status_now = (fields.get("status") or {}).get("name", "")
        status = least_advanced(tasks)
        target = cfg.transitions.get(status)
        title = f"{key} ({engs}) {fields.get('summary', '')!r}"
        if status == "To build" and not target:
            report.append(f"{title}: not started, nothing to report")
            continue
        folder = proofs_root(cfg)
        proofs = [p for t in tasks if t.status != "To build" and (p := find_proof(t.eng, folder))] if cfg.attach_proofs else []
        on_issue = {a.get("filename") for a in fields.get("attachment") or []}
        for proof in proofs:
            if proof.filename in on_issue:
                report.append(f"      proof {proof.filename} already attached")
            elif jira.apply:
                jira.attach(key, proof, [t.eng for t in tasks])
                jira.audit(action="attach", issue=key, eng=proof.eng, file=proof.filename)
                report.append(f"      attached {proof.filename}")
            else:
                report.append(f"      would attach {proof.filename} ({proof.pdf.stat().st_size // 1024} KB)")
        comments = jira.request("GET", f"/rest/api/3/issue/{key}/comment", {"maxResults": "100", "orderBy": "-created"})
        note = cfg.notes.get(key, "")
        lines = comment_lines(key, tasks, today, note, proofs)
        if already_posted(comments, key, tasks, note, proofs):
            report.append(f"{title}: up to date ({status})")
        elif jira.apply:
            jira.request("POST", f"/rest/api/3/issue/{key}/comment", payload=comment_body(lines))
            jira.audit(action="comment", issue=key, eng=engs, status=status, ref=fingerprint(key, tasks, note, proofs))
            report.append(f"{title}: commented ({status})")
        else:
            report.append(f"{title}: would comment ({status})")
            if show:
                report += [f"      | {line}" for line in lines]
        if target and target != status_now:
            if not forward(cfg.jira_status_order, status_now, target):
                report.append(f"      not moving {status_now!r} -> {target!r} (only forward)")
                continue
            options = jira.request("GET", f"/rest/api/3/issue/{key}/transitions").get("transitions", [])
            move = next((t for t in options if (t.get("to") or {}).get("name") == target), None)
            if move is None:
                report.append(f"      no transition to {target!r} from {status_now!r} in this workflow")
            elif jira.apply:
                jira.request("POST", f"/rest/api/3/issue/{key}/transitions", payload={"transition": {"id": move["id"]}})
                jira.audit(action="transition", issue=key, eng=engs, from_status=status_now, to_status=target)
                report.append(f"      moved {status_now!r} -> {target!r}")
            else:
                report.append(f"      would move {status_now!r} -> {target!r}")
    return report


# --- matching differently worded issues ------------------------------------------------------------

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


def search_mine(jira: Jira, fields: str) -> list[dict[str, Any]]:
    jql = f'project = "{jira.cfg.project_key}" AND assignee = "{jira.cfg.allen_account_id}" ORDER BY key'
    found, token = [], None
    while True:
        query = {"jql": jql, "fields": fields, "maxResults": "100"}
        if token:
            query["nextPageToken"] = token
        page = jira.request("GET", "/rest/api/3/search/jql", query)
        found += page.get("issues", [])
        token = page.get("nextPageToken")
        if not token or page.get("isLast", True):
            return found


def discover(jira: Jira) -> list[str]:
    """Read only: Allen's issues in the project, each matched to a task of Allen's."""
    jira.check_identity()
    found = search_mine(jira, "summary,description,status,assignee")
    texts = build_list_texts()
    issues = [(i["key"], f"{(i.get('fields') or {}).get('summary', '')}\n{adf_text((i.get('fields') or {}).get('description'))}")
              for i in found]
    matches = match_issues(issues, texts)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "proposed_matches.json").write_text(json.dumps([m.__dict__ for m in matches], indent=2, ensure_ascii=False),
                                              encoding="utf-8")
    lines = [f"{len(found)} issues of {jira.cfg.allen_display_name} in {jira.cfg.project_key}; "
             f"{sum(m.confident for m in matches)} matched confidently. Nothing in Jira was changed.", ""]
    for m in matches:
        mark = "OK " if m.confident else "?? "
        runner = f", next {m.runner_up[0]} {m.runner_up[1]:.2f}" if m.runner_up else ""
        lines.append(f"{mark}{m.issue} -> {m.eng or '-'} ({m.score:.2f}{runner}; {m.reason})  {m.summary}")
    lines += ["", f"Saved: {OUT / 'proposed_matches.json'}. Next: `approve` copies the OK lines into "
                  "settings/jira_sync.toml; map the others by hand."]
    return lines


def approve(cfg: Config, path: Path = CONFIG, proposals: Path = OUT / "proposed_matches.json") -> list[str]:
    """Copy the confident matches from the last `discover` into [issues], without
    changing any line already there. Touches only the local settings file."""
    matches = json.loads(proposals.read_text(encoding="utf-8"))
    new = {m["issue"]: m["eng"] for m in matches if m["confident"] and m["eng"] and m["issue"] not in cfg.issues}
    if not new:
        return ["nothing new to approve"]
    text = path.read_text(encoding="utf-8")
    added = [f'"{key}" = ["{eng}"]   # approved from discover' for key, eng in sorted(new.items())]
    header = re.search(r"^\[issues\][^\n]*\n", text, re.M)
    if header is None:
        text = text.rstrip("\n") + "\n\n[issues]\n" + "\n".join(added) + "\n"
    else:  # right under [issues], so they never land in a later table
        text = text[:header.end()] + "\n".join(added) + "\n" + text[header.end():]
    path.write_text(text, encoding="utf-8")
    Config.load(path)  # still valid, or this raises
    return ["added to settings/jira_sync.toml [issues]:"] + added


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
                lines = run_sync(jira, show=args.command == "plan")
            print("\n".join(lines))
            if not args.every:
                return 0
            time.sleep(args.every * 60)
    except GuardError as exc:
        print(f"STOPPED by a guardrail: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
