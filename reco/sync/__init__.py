"""The engine sync (ENG-04, SD module "sync").

Reads postevents, orders and recommendationrequests by updated_at (and, with
ENG-29, rec_serve_log) through the platform module, writes the engine copies
through the store module, keeps checkpoints, and runs the backfill and the daily
reconciliation. POST /v1/events is retired (DS-017 v2.5 section 7).
"""
