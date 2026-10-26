# Continue on another laptop

Everything needed to carry on is in this repository, on branch
`wave1a/foundations`, except **`.env`** (the database logins), which never goes
into git. Last updated 3 Oct 2026 (Windows steps added); the work itself is as of 1 Oct, the end of ENG-08 and the audit.

## 1. Set up the new laptop (about 15 minutes)

> [!note] **On Windows**, use one of these two ways:
> - **WSL (recommended):** install WSL with Ubuntu (`wsl --install` in an admin
>   PowerShell, then restart), and do everything below inside the Ubuntu terminal,
>   exactly as written. Clone the repo inside Ubuntu (e.g. `~/SocoRecommendation`),
>   not under `/mnt/c`, so it stays fast. Claude Code can run inside WSL too.
> - **Plain Windows:** see "Windows without WSL" at the end of this section.

```bash
git clone <the repo URL> SocoRecommendation
cd SocoRecommendation
git checkout wave1a/foundations

python3.12 -m venv .venv                 # Python 3.12 (RE-00a)
.venv/bin/pip install -r requirements.txt
```

**Copy `.env` by hand** from the old laptop: AirDrop, a USB stick, or a password
manager. Never through git, email, WhatsApp or a shared document. It holds:

| Key | What |
|---|---|
| `ENGINE_ENV` | `dev` |
| `APP_MONGO_URI`, `APP_MONGO_DB` | SOCO's platform database (read-only login `SocoReadonly`), db `soco` on `nex-dev.cob9whd` |
| `ML_MONGO_URI`, `ML_MONGO_DB` | the engine's database, db `SoCo` on `soco.4b7z1ko` |
| `SETTINGS_FILE` | `settings/engine.toml` |
| `INGEST_TOKEN` | the serving token, if one was generated (`scripts/generate_ingest_token.py`) |
| others | see `.env.example` |

**Atlas network access:** add the new laptop's IP to both clusters' access lists
(or ask Aravinth to), or the database steps below fail with a timeout. If runs are
very slow or DNS fails ("no nameservers"), set DNS to `1.1.1.1` and `8.8.8.8`.

**Check it works:**

```bash
.venv/bin/python scripts/setup_engine_db.py        # "16 of 16 collections present"
.venv/bin/python -m pytest -q                      # 634 passed, 1 skipped on 1 Oct
bash scripts/run_checklist.sh                      # 67 of 68 on 1 Oct (6.4 waits on question 17)
```

**Obsidian:** open the `obsidian/` folder as a vault. Start at `Home`. (On WSL,
Obsidian runs on Windows: open `\\wsl$\Ubuntu\home\<you>\SocoRecommendation\obsidian`.)

### Windows without WSL

Install **Python 3.12** (python.org; tick "Add to PATH") and **Git for Windows**
(it brings Git Bash, which runs the checklist). In PowerShell:

```powershell
git clone <the repo URL> SocoRecommendation
cd SocoRecommendation
git checkout wave1a/foundations
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Then everywhere the docs say `.venv/bin/python`, use `.venv\Scripts\python.exe`:

```powershell
.venv\Scripts\python.exe scripts\setup_engine_db.py
.venv\Scripts\python.exe -m pytest -q
```

Run the checklist from **Git Bash** (not PowerShell): `bash scripts/run_checklist.sh`.
It finds the Windows Python and the right `sed` by itself. A one-off setting such
as `ML_MONGO_DB=reco_demo` in front of a command works in Git Bash; in PowerShell
set it first: `$env:ML_MONGO_DB="reco_demo"` (and `Remove-Item Env:ML_MONGO_DB`
afterwards).

> [!warning] The checklist was made portable on 3 Oct but has only been run on
> macOS. If a line fails on Windows only, it is most likely the shell, not the
> engine. Run it under WSL to tell the two apart.

## 2. Bring Claude up to speed

Claude Code keeps its own notes about you and the project outside the repo. A
copy is in `.claude/memory/`. Put them where Claude Code looks on the new laptop:

Claude names that folder after the repo's full path, with every character that
is not a letter or a digit turned into `-` (`/Users/offx.all3n/vultrx/SocoRecommendation`
became `-Users-offx-all3n-vultrx-SocoRecommendation`). Run this in the repo folder:

macOS, Linux or WSL:

```bash
DIR="$HOME/.claude/projects/$(pwd | sed 's/[^A-Za-z0-9]/-/g')/memory"
mkdir -p "$DIR" && cp .claude/memory/*.md "$DIR/"
```

Windows (PowerShell):

```powershell
$dir = Join-Path $env:USERPROFILE (".claude\projects\" + ((Get-Location).Path -replace '[^A-Za-z0-9]','-') + "\memory")
New-Item -ItemType Directory -Force $dir | Out-Null
Copy-Item .claude\memory\*.md $dir
```

If Claude doesn't seem to know the project afterwards: start Claude Code in the
repo once, look in `~/.claude/projects/` (Windows: `%USERPROFILE%\.claude\projects\`)
for the folder it created, and copy the files into its `memory` folder.

Then start Claude Code in the repo and paste this as the first message:

> Read `CLAUDE.md`, `Tracing/CONTINUE_ON_ANOTHER_LAPTOP.md`, `Tracing/REALIGNMENT_v1.3.md`, `Tracing/AUDIT_2026-10-01.md` and `obsidian/Tasks/Task Board.md`. The spec is only `docs/updated` (its text is in `Tracing/pack_text/`). Tell me where we are, then continue with the next task.

`CLAUDE.md` and the `update-docs` skill (`.claude/skills/update-docs/`) are in the
repo, so the working rules come along automatically.

## 3. Where things stand (1 Oct 2026)

| Task | State | Notes |
|---|---|---|
| ENG-01 | Waiting | Dev done (16 collections). Test and production servers and clusters wait on Aravinth |
| ENG-02 | Built | Skeleton, health, logs, live settings (version 3; Fixed-for-Wave-1A values locked) |
| ENG-03 | Built | Reading SOCO's data; one source per kind; no event source switch |
| ENG-04 | Built | Engine sync; real backfill into dev `SoCo` done 1 Oct |
| ENG-05 | Built | Method per user (SHA-256 buckets); policy_id names the methods |
| ENG-06 | In progress | Serving works with interim newest-first lists; real ranking waits on ENG-09, ENG-17, ENG-19 |
| ENG-07 | Built | Nightly batches at 2 AM IST, `ml_job_runs`, kill-safe |
| ENG-08 | Built | E-01 to E-12; two answers from Aravinth pending (questions 16, 17) |
| ENG-29 | Built | Adapters; category map still empty (your decision) |

Every row above was audited line by line against the pack on 1 Oct:
`Tracing/AUDIT_2026-10-01.md`.

## 4. Open items

**Waiting on Aravinth** (`Tracing/REALIGNMENT_v1.3.md`, questions 16 and 17):
1. Which fields in `followers` hold a block (blocker, blocked, status)?
2. Does an account with no `status` count as active? Until answered, no product
   on dev can be served (checklist 6.4 fails).

Read access to the backend code would answer both.

**Waiting on you:**
- The category map (`[lists] category_map` in `settings/engine.toml`, then raise
  `config_version`). `python -m reco.jobs category_check` lists the 42 labels outside
  the 23; the two "Menswear catimp…" import categories hold 2,005 products.
- Generate the serving token and give it to Aravinth privately, once a test server exists.

**Keep the dev copy current:** SOCO deletes events after 90 days. Run
`.venv/bin/python -m reco.jobs sync_loop` while working (it copies every 5 minutes),
or `python -m reco.jobs sync` once a day.

## 5. Next steps, in the pack's order

1. **ENG-09** fallback ladder (rungs 1 to 5). Then ENG-06 can drop its interim list.
2. **ENG-10** interest score on live data: move M1 onto `ml_events` (the old reader still reads live `postevents`).
3. **ENG-11** M1 check script.
4. Then Step 3: ENG-12 to ENG-17, ENG-27, ENG-28.

For each task:
- follow `CLAUDE.md`: build, test, update the technical doc and the Obsidian notes, add checklist lines, commit, push;
- then audit its row line by line against the pack before calling it done.

## 6. Where to find things

| What | Where |
|---|---|
| The spec (never edit) | `docs/updated/` |
| The spec as searchable text | `Tracing/pack_text/` (regenerate with `python3 scripts/extract_pack.py`) |
| What changed in pack v1.3, and every question with its answer | `Tracing/REALIGNMENT_v1.3.md` |
| The audit | `Tracing/AUDIT_2026-10-01.md` |
| Checklist runs | `Tracing/checks/` |
| Technical docs, one per task | `docs/engineering/ENG-xx.md` |
| Plain-language notes, demos, task board | `obsidian/` |
| Every check, end to end | `scripts/run_checklist.sh` |
| Settings | `settings/engine.toml` |
| Claude's notes about you and the project | `.claude/memory/` |
