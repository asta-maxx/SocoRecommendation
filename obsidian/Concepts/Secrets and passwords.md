---
tags: [concept, security]
---
# Secrets and passwords

**Secrets** are the logins and keys the engine uses: the database passwords (inside the connection strings) and tokens that prove "this request really is from SOCO_BE":
- the **serving token** (`INGEST_TOKEN`), which SOCO_BE sends when it asks for a list (`POST /v1/recommendations`). The name is left over from the retired events door (`POST /v1/events`); it now guards serving only;
- later, an **admin token** (`ADMIN_TOKEN`) for the fraud case screens (ENG-21).

## The rule
Secrets live **only in the server's own settings**. Never in code, never in a shared file, never in a chat.

## Why it matters here
A live SOCO database password was once shared in circulated files. That's why Aravinth is making a **new read-only login** (task DB-02) and retiring the old one.

## The `.env` file
- On my laptop, secrets sit in a file called `.env`. It's convenient for dev and test.
- It's **never uploaded to git**: it's listed in `.gitignore`.
- In **production**, the engine **ignores `.env` completely**. If it detects that production was switched on from a `.env` file, it **refuses to start**.

> [!warning] The engine never prints a connection string in its messages, because that would leak the password.

## How this connects
- Enforced in → [[ENG-01 - Engine home and databases]].
- Matters most in the production setup → [[Environments]].
- The login to SOCO's data is → [[Platform Database]].
