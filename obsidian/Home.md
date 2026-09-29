---
tags: [home]
---
# SOCO Recommendation Engine: start here

This vault explains, in plain words, what I'm building and why. Every note ends with **How this connects**, so you can follow the thread from one idea to the next.

> [!tip] Open the **Graph view** (left sidebar) to see how everything links together.

## The story so far
1. **SOCO** is a shopping-and-social app → [[SOCO App]]
2. Before this project I built a small demo of one piece → [[Before Wave 1A - the M1 demo]]
3. Now we're building the full thing, called **Wave 1A** → [[Wave 1A]]
4. The rules for it are in a set of five documents → [[The Pack]]
5. Three people are involved → [[People]]
6. The work is split into steps → [[Build Steps]]

## The main pieces
- [[Recommendation Engine]]: what I'm building
- [[SOCO_BE]]: the app's backend, which talks to my engine
- [[Platform Database]]: SOCO's data, which I only read
- [[Engine Database]]: my own data, which I write
- [[MongoDB Atlas]]: where both databases live
- [[Environments]]: dev, test and production
- [[Collections]] and [[Indexes]]: how data is organised inside a database
- [[Secrets and passwords]]: keeping logins safe
- [[Settings file]]: every tunable number, in one place
- [[Logs]]: the engine's diary
- [[Event source switch]]: moving from SOCO's old logs to the new one, day by day

## Tasks
- [[Task Board]]: every task and where it stands
- [[ENG-01 - Engine home and databases]]: laptop part done; waiting on servers
- [[ENG-02 - Service skeleton and settings]]: built; check passed on laptop
- [[ENG-03 - Reading SOCO's data correctly]]: built; check passed on laptop

## Demos
- [[How to demo a task]]: how every demo is run
- [[Demo - ENG-01]]: the engine's home and databases
- [[Demo - ENG-02]]: skeleton, health check, logs, live settings
- [[Demo - ENG-03]]: reading SOCO's data correctly
