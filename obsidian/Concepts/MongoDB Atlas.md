---
tags: [concept, database]
---
# MongoDB Atlas

**MongoDB** is the kind of database SOCO uses. It stores data as flexible "documents", like filled-in forms, rather than rigid tables.

**Atlas** is MongoDB's cloud service: someone else runs the servers, and we just use them.

## Words to know
- **Cluster:** a group of servers in Atlas. We have two:
  - `nex-dev.cob9whd`: **SOCO's** cluster, which holds the [[Platform Database]].
  - `soco.4b7z1ko`: **my build** cluster, which holds my dev [[Engine Database]].
- **Database:** a named container inside a cluster, for example `soco` or `SoCo`.
- **Connection string:** the address plus login used to reach a cluster. It contains a password, so it's a secret → [[Secrets and passwords]].

## Two quirks I've hit
- **A paused cluster looks like a security error.** When a cluster pauses itself, the error mentions TLS, which sounds like a certificate problem, but it just needs resuming in Atlas.
- **Database names are case-sensitive.** A wrong-case name gives no error, just empty results.

## How this connects
- Holds both → [[Platform Database]] and [[Engine Database]].
- Organised into → [[Collections]].
