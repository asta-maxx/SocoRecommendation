---
tags: [demo, guide]
---
# How to demo a task

Each finished task has its own demo note. This page explains how every demo is put together, so they all run the same way.

## The idea
A demo proves one thing: **the task's check in the Build List passes**. Every task in [[The Pack]] ends with a *"How to check it is done"* line. The demo acts that check out, live, in front of someone.

> [!tip] Start by reading the check out loud. Then show it passing. The audience always knows what they're looking for.

## Before any demo
0. **Run the checklist:** `bash scripts/run_checklist.sh`. If everything passes, the demo will work → [[Checklist]].
1. **Open the repo in a terminal:** `cd ~/vultrx/SocoRecommendation`.
2. **Make sure the build cluster is awake.** Paused Atlas clusters look like a security (TLS) error. If a command hangs or complains about TLS, resume the cluster in Atlas → [[MongoDB Atlas]].
3. **Have two or three terminal windows ready:** one for the engine, one or two for commands.
4. **Never show the `.env` file on screen.** It holds the database passwords → [[Secrets and passwords]]. None of the demo commands print it.

## Safe by design
- Anything that **writes** during a demo uses a **throwaway database** called `reco_demo`, never the real dev database `SoCo`. Then the demo leaves nothing behind in the real diary or scores → [[Engine Database]].
- Anything that **reads SOCO's data** only reads. The login can't change anything → [[Platform Database]].
- After the demo, delete `reco_demo` in Atlas: **Browse Collections → reco_demo → Drop Database**.

## How each demo note is laid out
- **What this demo proves:** the check, in plain words.
- **Setup:** anything to start before the audience watches.
- **Steps:** each one has three parts:
  - **Say:** one sentence to tell the audience;
  - **Run:** the command to type;
  - **They should see:** what appears on screen.
- **What you can't show yet,** and why. Being upfront beats being caught out.
- **Clean up.**

## If something goes wrong
- A command hangs for about 10 seconds, then fails: the cluster is probably paused. Resume it and retry.
- **`ConfigurationError: no nameservers`**: the laptop couldn't look up Atlas's address, because for a moment it had no DNS server. This happens when Wi-Fi reconnects or a VPN switches. Wait a few seconds and run the command again. To check, run `cat /etc/resolv.conf`; it should list a `nameserver`. If it keeps happening, switch the VPN off or on, or set DNS to `1.1.1.1` and `8.8.8.8` in System Settings → Network → Wi-Fi → Details → DNS. Seen on 28 Sep 2026; it passed on the next run.
- An unexpected result: say so, and note it. A demo that finds a real problem has done its job.

## The demos
- [[Demo - ENG-01]]: the engine's home and databases (about 5 minutes)
- [[Demo - ENG-02]]: the skeleton, health check, logs and live settings (about 10 minutes)
- [[Demo - ENG-03]]: reading SOCO's data correctly (about 5 minutes, read-only)
- [[Demo - ENG-04]]: receiving activity events (about 7 minutes)

## How this connects
- Every demo acts out a task's check from → [[Task Board]].
- The written check results live in the repo under `Tracing/checks/`.
