---
tags: [demo]
task: ENG-06
duration: about 8 minutes
---
# Demo: ENG-06, ask for a list, check its receipt, switch a surface off

> [!note] Since 1 Oct (ENG-29) the settings file is **version 3**. Where the outputs below show version 2 (`cfg2…`, `config_version 2`), a rehearsal today shows 3. Nothing else changes.

## What this demo proves
The Build List's check for ENG-06: *"A request returns within 200 ms on test, and one request record exists with served_items matching the response. Setting a surface to off returns 503."*

It also shows the password check, a refused surface, and the stand-in order (newest suitable posts first) that the engine serves until the real rankings exist. → [[ENG-06 - Serve a recommendation list]]

> [!important] Both surfaces are **off** in the real settings file, as the pack requires for now. So this demo runs on a **throwaway copy** of the settings with both switched on, a **throwaway database** (`reco_demo`) for the receipts, and a **throwaway password**. The real settings, the real diary in `SoCo` and the real serving password are never touched or shown.

> [!note] Rehearsed on 1 Oct 2026 on my laptop against SOCO's dev data (8 posts, 2,011 products). The settings file was at **version 2**, so the change in step 6 makes version **3**. If the file has moved on, use the next number up. The official 200 ms check is on the test server; the laptop numbers include the trip to Atlas.

## Setup (before the audience watches)
**Terminal A** runs the engine. Copy the settings, switch both surfaces on in the copy, and start the engine on the copy, the throwaway database and a made-up password:
```bash
cp settings/engine.toml /tmp/soco-serve.toml
sed -i '' 's/^surface_mode_feed = "off"/surface_mode_feed = "live"/; s/^surface_mode_product = "off"/surface_mode_product = "live"/' /tmp/soco-serve.toml
INGEST_TOKEN=demo-only-token SETTINGS_FILE=/tmp/soco-serve.toml ML_MONGO_DB=reco_demo \
  .venv/bin/python -m uvicorn reco.main:app --port 8100
```
Wait for `Application startup complete`. Keep this window visible: the log lines are part of the show.

**Terminal B** is for the commands below, from the repo folder.

> [!tip] The password here is made up for the demo and only lives in these two commands. Never type the real `INGEST_TOKEN` on screen.

## Steps

### 1. No password, no list
- **Say:** "Only SOCO's backend may ask for lists. A wrong password is turned away."
- **Run (B):**
  ```bash
  curl -s -X POST http://127.0.0.1:8100/v1/recommendations -H "Authorization: Bearer wrong" \
    -d '{"user_id":"64f1c0ffee0000000000abcd","surface":"feed","page":1,"limit":5,"session_id":"ses_demo"}' -w "\nHTTP %{http_code}\n"
  ```
- **They should see:**
  ```
  {"error":"unauthorized","detail":"missing or wrong bearer token"}
  HTTP 401
  ```
  → [[Secrets and passwords]]

### 2. Only feed and product exist
- **Say:** "Wave 1A has two surfaces. Anything else is a mistake, and the engine says what's wrong."
- **Run (B):**
  ```bash
  curl -s -X POST http://127.0.0.1:8100/v1/recommendations -H "Authorization: Bearer demo-only-token" \
    -d '{"user_id":"64f1c0ffee0000000000abcd","surface":"opportunity","page":1,"limit":5,"session_id":"ses_demo"}' -w "\nHTTP %{http_code}\n"
  ```
- **They should see:**
  ```
  {"error":"invalid_surface","detail":"surface must be feed or product"}
  HTTP 400
  ```

### 3. Ask for a feed list
- **Say:** "Now a real request: five items of the For You feed for one user. Watch the time."
- **Run (B):**
  ```bash
  curl -s -X POST http://127.0.0.1:8100/v1/recommendations -H "Authorization: Bearer demo-only-token" \
    -d '{"user_id":"64f1c0ffee0000000000abcd","surface":"feed","page":1,"limit":5,"session_id":"ses_demo"}' \
    -o /tmp/eng06-feed.json -w "HTTP %{http_code} in %{time_total}s\n"
  python3 -m json.tool /tmp/eng06-feed.json
  ```
- **They should see** (IDs abridged):
  ```
  HTTP 200 in 0.085629s
  {
      "request_id": "d164665b-51aa-4420-ab94-4bd303ef90a5",
      "policy_id": "cfg2.interest-recency_decay.promoter_score-cohort_percentile",
      "model_version": "1.0.0",
      "config_version": "2",
      "fallback_step": null,
      "is_exploration": false,
      "items": [
          {"item_id": "6a9fd06d…5570", "item_type": "post", "post_id": "6a9fd06d…5570",
           "product_id": null, "position": 1, "reason_code": null},
          … positions 2 to 5 …
      ]
  }
  ```
- **Point out:**
  - `request_id`: a fresh ID for this one list. Every tap on it will carry this ID.
  - `policy_id`: settings version 2, and the method this user gets in each slot, by name: *recency decay* for interest, *cohort percentile* for the promoter score. → [[ENG-05 - Same method for each user]]
  - `fallback_step` is empty: nothing is ranked yet, so no plan B was needed.
  - Items are SOCO's newest suitable posts, numbered from 1: the stand-in order until the real ranking.

  Window A shows a `"served list"` line with the same `request_id`. → [[Logs]]

### 4. The receipt matches the answer
- **Say:** "Before the answer left, the engine filed a receipt. Here it is, read back from the engine's own database."
- **Run (B):**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_served_list.py /tmp/eng06-feed.json
  ```
- **They should see:**
  ```
  records for this request_id: 1
  {'event_code': 'E1', 'source': 'engine', 'surface': 'feed', 'policy_id': 'cfg2.interest-recency_decay.promoter_score-cohort_percentile', 'fallback_step': None, 'is_exploration': False, 'ordering': 'interim_newest_first'}
  server_ts: 2026-10-01T09:25:05.784+00:00
  slots: {'interest': 'recency_decay', 'promoter_score': 'cohort_percentile'}
  5 candidate ids, 5 served, 5 in the sample
  served_items match the response: True
  ```
- **Point out:** exactly **one** receipt, and what it says was shown is exactly what was sent. `ordering` says this is the stand-in list, so nobody will mistake it for a ranked one. → [[Activity events]]

### 5. Twenty lists, timed, every receipt checked
- **Say:** "One request is a story. Here's the check itself: twenty requests on each surface, the time 95 in 100 come back within, and every receipt compared."
- **Run (B):**
  ```bash
  INGEST_TOKEN=demo-only-token ML_MONGO_DB=reco_demo .venv/bin/python scripts/try_recommendations.py http://127.0.0.1:8100 feed
  INGEST_TOKEN=demo-only-token ML_MONGO_DB=reco_demo .venv/bin/python scripts/try_recommendations.py http://127.0.0.1:8100 product
  ```
- **They should see:**
  ```
  feed: HTTP 200 x19, 8 items, policy_id cfg2.interest-recency_decay.promoter_score-cohort_percentile, fallback_step None
    first items: ['6b5570:post', 'f2a67d:post', '69a2d1:post']
    p95 69 ms (median 62 ms) -> within 200 ms
    records with served_items matching the response: 19 of 19
  product: HTTP 200 x19, 10 items, policy_id cfg2.product_ranking-bought_together, fallback_step None
    first items: ['869e45:product', '869ddd:product', '869d37:product']
    p95 93 ms (median 82 ms) -> within 200 ms
    records with served_items matching the response: 19 of 19
  ```
- **Point out:** the feed has only 8 suitable posts on dev, so it returns 8 although 10 were asked for. That's the rule: exactly the number asked, unless fewer exist. Product rails never include the product being viewed. (The first request warms up and isn't timed, hence 19.)

### 6. Switch the feed off, without a restart
- **Say:** "Now the emergency brake. I switch the feed off in the settings while the engine runs."
- **Run (B):**
  ```bash
  sed -i '' 's/config_version = "2"/config_version = "3"/; s/changed_by = "Allen"/changed_by = "Demo"/; s/^surface_mode_feed = "live"/surface_mode_feed = "off"/' /tmp/soco-serve.toml
  ```
- **They should see**, in window A within **30 seconds**:
  ```json
  {"ts": "2026-10-01T09:25:34.736Z", "level": "INFO", "logger": "reco.settings", "message": "settings changed", "env": "dev",
   "config_version": "3", "previous_version": "2", "changed_by": "Demo", "changed_keys": ["serving.surface_mode_feed"], "recorded": true}
  ```
- **Then run (B)** the feed request from step 3 without saving it, and a product one:
  ```bash
  curl -s -X POST http://127.0.0.1:8100/v1/recommendations -H "Authorization: Bearer demo-only-token" \
    -d '{"user_id":"64f1c0ffee0000000000abcd","surface":"feed","page":1,"limit":5,"session_id":"ses_demo"}' -w "\nHTTP %{http_code}\n"
  curl -s -X POST http://127.0.0.1:8100/v1/recommendations -H "Authorization: Bearer demo-only-token" \
    -d '{"user_id":"64f1c0ffee0000000000abcd","surface":"product","context_item_id":"64f1c0ffee0000000000abcd","page":1,"limit":3,"session_id":"ses_demo"}' \
    -o /dev/null -w "product: HTTP %{http_code}\n"
  ```
- **They should see:**
  ```
  {"error":"surface_off","detail":"the feed surface is off"}
  HTTP 503
  product: HTTP 200
  ```
- **Say:** "503 here means 'use your own list'. SOCO's backend falls back at once and the shopper never notices. Product keeps serving: each surface has its own switch." → [[Settings file]], [[SOCO_BE]]

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| The 200 ms check **on the test server** | The pack measures it there, and it doesn't exist yet. This demo is laptop to Atlas | The test server ([[ENG-01 - Engine home and databases]]) |
| A **ranked** list | The stand-in order is newest first | ENG-19 (feed), ENG-17 (product) |
| A plan-B step on the answer | The fallback ladder isn't built, so `fallback_step` is always empty | ENG-09 |
| The full safety filters (blocks, mutes, private accounts…) | Only the stand-in check runs: public, not hidden, not removed; product active and in stock | ENG-08 |
| Page 2 leaving out what you saw in the last 24 hours | Part of the ranking layer | ENG-19 |
| Internal mode on production test accounts | No production server yet. It's covered by an automatic test (a listed account gets a list, others get 503) | The servers; test accounts in the settings |

## Clean up
1. Stop window A with Ctrl+C.
2. In Atlas: **Browse Collections → reco_demo → Drop Database.**
3. `/tmp/soco-serve.toml` and `/tmp/eng06-feed.json` can stay or be deleted; nothing reads them.

## How this connects
- Proves → [[ENG-06 - Serve a recommendation list]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-05]]
- Next demo → [[Demo - ENG-07]]
