---
tags: [demo]
task: ENG-04
duration: about 7 minutes
---
# Demo: ENG-04, receiving activity events

## What this demo proves
The Build List's check for ENG-04: *"Send the same batch twice: the second reply shows all duplicates. An event with position 0 is rejected with a reason."* It also shows that the front door is locked without the token. → [[ENG-04 - Receiving activity events]]

> [!important] It uses a **throwaway token** and the throwaway database `reco_demo`. Your real token (once you make it) and the real dev log are never touched.

## Setup (before the audience watches)
**Window A: the engine,** with a throwaway token:
```bash
cd ~/vultrx/SocoRecommendation
TOK=$(.venv/bin/python scripts/generate_ingest_token.py)
echo "$TOK" > /tmp/soco-demo-token
cp settings/engine.toml /tmp/soco-demo.toml
INGEST_TOKEN=$TOK SETTINGS_FILE=/tmp/soco-demo.toml ML_MONGO_DB=reco_demo .venv/bin/python -m uvicorn reco.main:app --port 8100
```
Wait for `Application startup complete`.

**Window B: the commands.** Load the token, and write the demo batch: an impression, a click, an add-to-cart, and one **bad** impression with position 0.
```bash
cd ~/vultrx/SocoRecommendation
TOK=$(cat /tmp/soco-demo-token)
cat > /tmp/soco-batch.json <<'EOF'
{"events": [
 {"event_id": "0b6f6f3e-3c1e-4d8a-9f1a-2b1f7c1d0a01", "event_name": "recommendation_impression", "user_id": "65f1a2b3c4d5e6f708192a3b",
  "server_ts": "2026-09-29T09:15:30.010Z", "request_id": "3f1c9a2e-7b4d-4e21-9c8a-5d6e7f8a9b0c", "item_id": "6a3fe5cfcce0b0785136e7fe",
  "item_type": "product", "position": 1, "viewport_entered": true, "dwell_ms": 2400, "is_exploration": false, "client_ts": "2026-09-29T14:45:29+05:30"},
 {"event_id": "0b6f6f3e-3c1e-4d8a-9f1a-2b1f7c1d0a02", "event_name": "recommendation_click", "user_id": "65f1a2b3c4d5e6f708192a3b",
  "server_ts": "2026-09-29T09:15:31.002Z", "request_id": "3f1c9a2e-7b4d-4e21-9c8a-5d6e7f8a9b0c", "item_id": "6a3fe5cfcce0b0785136e7fe",
  "item_type": "product", "position": 1},
 {"event_id": "0b6f6f3e-3c1e-4d8a-9f1a-2b1f7c1d0a03", "event_name": "add_to_cart", "user_id": "65f1a2b3c4d5e6f708192a3b",
  "server_ts": "2026-09-29T09:16:05.000Z", "request_id": "3f1c9a2e-7b4d-4e21-9c8a-5d6e7f8a9b0c", "product_id": "6a3fe5cfcce0b0785136e7fe", "quantity": 1},
 {"event_id": "0b6f6f3e-3c1e-4d8a-9f1a-2b1f7c1d0a04", "event_name": "recommendation_impression", "user_id": "65f1a2b3c4d5e6f708192a3b",
  "server_ts": "2026-09-29T09:15:30.500Z", "request_id": "3f1c9a2e-7b4d-4e21-9c8a-5d6e7f8a9b0c", "item_id": "6a3fe5cfcce0b0785136e7ff",
  "item_type": "product", "position": 0}
]}
EOF
```

## Steps

### 1. Send a batch
- **Say:** "SOCO's backend will send what shoppers did in batches like this: four events, one of them deliberately wrong."
- **Run (B):**
  ```bash
  curl -s -X POST http://127.0.0.1:8100/v1/events -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" --data @/tmp/soco-batch.json; echo
  ```
- **They should see:**
  ```json
  {"accepted":3,"duplicates":0,"rejected":[{"event_id":"…0a04","reason":"position 0 is not allowed: positions count from 1"}]}
  ```
  Point out: three stored, and **the bad one refused with a reason**. That's half of the check.

### 2. Send the same batch again (a retry)
- **Say:** "Networks fail, so SOCO's backend retries. The engine must never store anything twice."
- **Run (B):** the same command as step 1.
- **They should see:** `{"accepted":0,"duplicates":3,…}`. **All duplicates.** That's the other half of the check.

### 3. The door is locked without the token
- **Say:** "Only SOCO's backend has the token."
- **Run (B):**
  ```bash
  curl -s -w "  HTTP %{http_code}\n" -X POST http://127.0.0.1:8100/v1/events -H "Content-Type: application/json" --data @/tmp/soco-batch.json
  ```
- **They should see:** `{"error":"unauthorized",…}  HTTP 401`.

### 4. What's in the log now
- **Say:** "Exactly three events, each stored once."
- **Run (B):**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_events.py
  ```
- **They should see:** `3 events`, with one each of `add_to_cart`, `recommendation_click` and `recommendation_impression`, and `switch date: not fixed yet`. → [[Activity events]]
- **Show window A:** a log line `"message": "events received"` with the counts. → [[Logs]]

### 5. (Optional) The daily comparison that sets the switch date
- **Say:** "Once SOCO's backend writes to both the old and new logs, a daily job compares them. After 7 matching days in a row, it fixes the switch date."
- **Run (B):**
  ```bash
  .venv/bin/python -m pytest tests/test_events_reconcile.py -q -k "seven_matching or breaks_the_run or no_events"
  ```
- **They should see:** `3 passed`: 7 good days fix the date, one bad day breaks the run, and empty days don't count. → [[Event source switch]]

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| SOCO's real backend sending events | Its side isn't built yet | Aravinth's APP-12 → [[People]] |
| The real token in use | I haven't generated and handed it over yet | Me |
| A real switch date | Needs 7 real days of both logs agreeing | APP-12, then 7 days |
| The check on the **test** server | It doesn't exist yet | Aravinth's hosting |

## Clean up
1. **Window A:** Ctrl+C.
2. **Window B:**
   ```bash
   rm -f /tmp/soco-demo-token /tmp/soco-batch.json
   .venv/bin/python -c "
   import asyncio; from pymongo import AsyncMongoClient; from reco.config import get_settings
   async def m():
       c=AsyncMongoClient(get_settings().ml_mongo_uri); await c.drop_database('reco_demo'); await c.close(); print('reco_demo dropped')
   asyncio.run(m())"
   ```

## How this connects
- Proves → [[ENG-04 - Receiving activity events]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-03]]
