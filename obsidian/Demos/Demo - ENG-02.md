---
tags: [demo]
task: ENG-02
duration: about 10 minutes
---
# Demo: ENG-02, skeleton, health check, logs and live settings

## What this demo proves
The Build List's check for ENG-02: *"Change a setting: it takes effect within a minute and is logged. Break the file: the service keeps running. Stop a database: /health returns 503."*

It also shows the 12 parts, the two ways to run, and the logs. → [[ENG-02 - Service skeleton and settings]]

> [!important] This demo changes settings, so it runs against a **throwaway copy** of the settings file and a **throwaway database** (`reco_demo`). The real settings file and the real diary in `SoCo` are never touched.

> [!note] Rehearsed on 1 Oct 2026, after the update to the new pack (v1.3). The settings file is now at **version 2**, so the change in step 5 makes version **3**. If the file's version has moved on again, use the next number up.

## Setup (before the audience watches)
**Terminal A** runs the engine. Copy the settings file, then start the engine on the copy and the throwaway database:
```bash
cp settings/engine.toml /tmp/soco-demo.toml
SETTINGS_FILE=/tmp/soco-demo.toml ML_MONGO_DB=reco_demo \
  .venv/bin/python -m uvicorn reco.main:app --port 8100
```
Wait for `Application startup complete`. Keep this window visible: its log lines are part of the show.

**Terminal B** is for the commands below. Open `/tmp/soco-demo.toml` in an editor, ready for step 5:
```bash
open -a "Visual Studio Code" /tmp/soco-demo.toml
```
> [!warning] Use VS Code, not TextEdit: TextEdit turns `"3"` into curly quotes, which breaks the file. The `code` command only works after VS Code → Cmd+Shift+P → **Shell Command: Install 'code' command in PATH**; `open -a` always works.
>
> **No editor?** Each editing step below also has a one-line command. It's the safest choice for a live demo.

## Steps

### 1. Twelve labelled parts, and two gatekeepers
- **Say:** "The engine is split into 12 parts, exactly as the pack lists them. Only one part may read SOCO's data, and only one may write. An automatic check enforces it."
- **Run (B):**
  ```bash
  ls reco
  .venv/bin/python -m pytest tests/test_module_layout.py -q
  ```
- **They should see:** the 12 folders (api, config, eligibility, fallback, fraud, jobs, monitoring, platform, ranking, slots, store, sync), then **16 passed**. `ls` also shows `__init__.py` and `main.py` (the package and its start-up wiring) and Python's `__pycache__`, which aren't modules. → [[Recommendation Engine]]
- **If asked "where are events?":** the new pack closed the event door. The **sync** part fetches SOCO's events instead. → [[Engine sync]]

### 2. One engine, two ways to run
- **Say:** "The same code runs as the API, which is what's running in window A, or as jobs that do the heavy work and stop."
- **Run (B):**
  ```bash
  .venv/bin/python -m reco.jobs --list
  ```
- **They should see:**
  ```
  interest
  reconcile_sync
  sync
  sync_check
  sync_loop
  ```
  `interest` is the interest-score job; the four `sync` jobs copy SOCO's events (ENG-04). ENG-07 adds the nightly jobs to this list. (Don't run any of them in the demo; they do real work and take a while.)

### 3. A health check that tells the truth
- **Say:** "The health page says OK only when both databases can be read."
- **Run (B):**
  ```bash
  curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8100/health
  ```
- **They should see:**
  ```
  {"status":"ok","environment":"dev", … ,"mongo":{"app":true,"ml":true}}
  HTTP 200
  ```
- **Now break a database.** In a **third terminal (C)**, start a second engine whose database address goes nowhere:
  ```bash
  ML_MONGO_URI="mongodb://127.0.0.1:1" MONGO_TIMEOUT_SECONDS=1 SETTINGS_FILE=/tmp/soco-demo.toml \
    .venv/bin/python -m uvicorn reco.main:app --port 8101
  ```
  When it has started, **run (B):**
  ```bash
  curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8101/health
  ```
- **They should see:**
  ```
  {"status":"unavailable","environment":"dev", … ,"mongo":{"app":true,"ml":false}}
  HTTP 503
  ```
  Stop window C with Ctrl+C. → [[Environments]]

### 4. Clear logs for every request
- **Say:** "Every request leaves one tidy line in the log."
- **Show window A.** Each `curl` above left a line like:
  ```json
  {"ts": "2026-10-01T09:06:04.405Z", "level": "INFO", "logger": "reco.request", "message": "request", "env": "dev",
   "method": "GET", "path": "/health", "status": 200, "duration_ms": 51.2}
  ```
  → [[Logs]]

### 5. Change a setting: in force within a minute, no restart
- **Say:** "Every tunable number lives in one file. I'll change one while the engine runs."
- **In the editor**, in `/tmp/soco-demo.toml`:
  - change `popularity_window_days = 30` to `45`;
  - change `config_version = "2"` to `"3"`;
  - change `changed_by = "Allen"` to `"Demo"`;
  - save.
- **Or run (B), without an editor:**
  ```bash
  sed -i '' 's/config_version = "2"/config_version = "3"/; s/changed_by = "Allen"/changed_by = "Demo"/; s/popularity_window_days = 30 /popularity_window_days = 45 /' /tmp/soco-demo.toml
  ```
- **They should see**, in window A within **30 seconds**:
  ```json
  {"ts": "2026-10-01T09:06:33.756Z", "level": "INFO", "logger": "reco.settings", "message": "settings changed", "env": "dev",
   "config_version": "3", "previous_version": "2", "changed_by": "Demo", "changed_keys": ["interest.popularity_window_days"], "recorded": true}
  ```
  → [[Settings file]]

### 6. The diary shows who changed what
- **Say:** "Every change is written down: when, old value, new value, who."
- **Run (B):**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_config_changes.py
  ```
- **They should see:**
  ```
  ml_config_changes in reco_demo (dev)

  2026-10-01T09:06:03+00:00  version 0 -> 2  by Allen
      (put in force; no values changed)

  2026-10-01T09:06:33+00:00  version 2 -> 3  by Demo
      interest.popularity_window_days: 30 -> 45
  ```
  The first entry is the engine starting on the file ("0" means nothing was in force before, in this fresh database).

### 7. Break the file: the engine keeps running
- **Say:** "Now a typo. The engine must shrug it off."
- **In the editor**, type `this is = not [valid` on the first line and save. **Or run (B):**
  ```bash
  { echo 'this is = not [valid'; cat /tmp/soco-demo.toml; } > /tmp/soco-demo.new && mv /tmp/soco-demo.new /tmp/soco-demo.toml
  ```
- **They should see**, in window A within 30 seconds, an **ERROR** line:
  ```json
  {"level": "ERROR", "logger": "reco.settings", "message": "settings file rejected; keeping the settings in force",
   "fault": "not valid TOML: Expected '=' after a key in a key/value pair (at line 1, column 6)", "config_version_in_force": "3", …}
  ```
  Then **run (B)** the health `curl` from step 3: still **HTTP 200**.
- *Optional:* fix the typo, change a number **without** raising `config_version`, and save. **Or run (B):**
  ```bash
  sed -i '' '1d' /tmp/soco-demo.toml
  sed -i '' 's/pool_size = 300 /pool_size = 250 /' /tmp/soco-demo.toml
  ```
  Window A shows another **ERROR** line: `"fault": "values changed but config_version is still '3': raise config_version for every change"`, and version 3 stays in force.

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| The check on the **test** server | The pack says every check runs on test. It doesn't exist yet, so this demo is on my laptop. The same steps work unchanged there | The test server ([[ENG-01 - Engine home and databases]]) |
| "Internal" mode serving test accounts | The setting exists, but there is no recommendation door to serve from yet | ENG-06; test accounts in the lists |
| The serving password in use | The check is ready, but no door uses it yet | ENG-06 |

## Clean up
1. Stop window A with Ctrl+C.
2. In Atlas: **Browse Collections → reco_demo → Drop Database.**
3. `/tmp/soco-demo.toml` can stay or be deleted; nothing reads it.

## How this connects
- Proves → [[ENG-02 - Service skeleton and settings]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-01]]
- Next demo → [[Demo - ENG-03]]
