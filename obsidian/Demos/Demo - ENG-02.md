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
> [!warning] Use VS Code, not TextEdit: TextEdit turns `"2"` into curly quotes, which breaks the file. The `code` command only works after VS Code → Cmd+Shift+P → **Shell Command: Install 'code' command in PATH**; `open -a` always works.
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
- **They should see:** the 12 folders (api, config, eligibility, events, fallback, fraud, jobs, monitoring, platform, ranking, slots, store), then **16 passed**. `ls` also shows `__init__.py` and `main.py` (the package and its start-up wiring) and Python's `__pycache__`, which aren't modules. → [[Recommendation Engine]]

### 2. One engine, two ways to run
- **Say:** "The same code runs as the API, which is what's running in window A, or as jobs that do the heavy work and stop."
- **Run (B):**
  ```bash
  .venv/bin/python -m reco.jobs --list
  ```
- **They should see:** `interest`, the interest-score job. (Don't run it in the demo; it does a real refresh and takes a while.)

### 3. A health check that tells the truth
- **Say:** "The health page says OK only when both databases can be read."
- **Run (B):**
  ```bash
  curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8100/health
  ```
- **They should see:** `"status":"ok"`, `"environment":"dev"`, `"mongo":{"app":true,"ml":true}`, and **HTTP 200**.
- **Now break a database.** In a **third terminal (C)**, start a second engine whose database address goes nowhere:
  ```bash
  ML_MONGO_URI="mongodb://127.0.0.1:1" MONGO_TIMEOUT_SECONDS=1 SETTINGS_FILE=/tmp/soco-demo.toml \
    .venv/bin/python -m uvicorn reco.main:app --port 8101
  ```
  When it has started, **run (B):**
  ```bash
  curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8101/health
  ```
- **They should see:** `"status":"unavailable"`, `"ml":false`, and **HTTP 503**. Stop window C with Ctrl+C. → [[Environments]]

### 4. Clear logs for every request
- **Say:** "Every request leaves one tidy line in the log."
- **Show window A.** Each `curl` above left a line like:
  ```json
  {"ts": "…Z", "level": "INFO", "logger": "reco.request", "message": "request", "env": "dev",
   "method": "GET", "path": "/health", "status": 200, "duration_ms": 61.7}
  ```
  → [[Logs]]

### 5. Change a setting: in force within a minute, no restart
- **Say:** "Every tunable number lives in one file. I'll change one while the engine runs."
- **In the editor**, in `/tmp/soco-demo.toml`:
  - change `popularity_window_days = 30` to `45`;
  - change `config_version = "1"` to `"2"`;
  - change `changed_by = "Allen"` to `"Demo"`;
  - save.
- **Or run (B), without an editor:**
  ```bash
  sed -i '' 's/config_version = "1"/config_version = "2"/; s/changed_by = "Allen"/changed_by = "Demo"/; s/popularity_window_days = 30 /popularity_window_days = 45 /' /tmp/soco-demo.toml
  ```
- **They should see**, in window A within **30 seconds**, a line with `"message": "settings changed"`, `"config_version": "2"`, `"changed_by": "Demo"` and `"changed_keys": ["interest.popularity_window_days"]`. → [[Settings file]]

### 6. The diary shows who changed what
- **Say:** "Every change is written down: when, old value, new value, who."
- **Run (B):**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_config_changes.py
  ```
- **They should see:**
  ```
  … version 0 -> 1  by Allen
      (put in force; no values changed)
  … version 1 -> 2  by Demo
      interest.popularity_window_days: 30 -> 45
  ```

### 7. Break the file: the engine keeps running
- **Say:** "Now a typo. The engine must shrug it off."
- **In the editor**, type `this is = not [valid` on the first line and save. **Or run (B):**
  ```bash
  { echo 'this is = not [valid'; cat /tmp/soco-demo.toml; } > /tmp/soco-demo.new && mv /tmp/soco-demo.new /tmp/soco-demo.toml
  ```
- **They should see**, in window A within 30 seconds, an **ERROR** line: `"settings file rejected; keeping the settings in force"`, with `"config_version_in_force": "2"`. Then **run (B)** the health `curl` from step 3: still **HTTP 200**.
- *Optional:* fix the typo, change a number **without** raising `config_version`, and save. It's rejected with *"raise config_version for every change"*.
  **Or run (B):**
  ```bash
  sed -i '' '1d' /tmp/soco-demo.toml
  sed -i '' 's/pool_size = 300 /pool_size = 250 /' /tmp/soco-demo.toml
  ```

## What you can't show yet
The pack says every check runs on the **test** server. It doesn't exist yet, so this demo is on my laptop. The same steps work unchanged on the test server once it's there.

## Clean up
1. Stop window A with Ctrl+C.
2. In Atlas: **Browse Collections → reco_demo → Drop Database.**
3. `/tmp/soco-demo.toml` can stay or be deleted; nothing reads it.

## How this connects
- Proves → [[ENG-02 - Service skeleton and settings]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-01]]
- Next demo → [[Demo - ENG-03]]
