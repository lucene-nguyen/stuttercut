# 0004 — SQLite for state and traces

- **Status:** Accepted
- **Date:** 2026-11-14
- **Jira:** LEARNING-234

## Context

The app needs durable state for jobs, transcript words, suggested and reviewed cuts, and
per-step spans for the Diagnostics screen. It runs on one machine with one user and one job at
a time. A database server would be another service to install and run on both Windows and
macOS.

## Decision

Use SQLite (Python standard library `sqlite3`) in a file under the `platformdirs` data folder.
Store jobs, words, cuts and spans there with versioned schema migrations. Media files and
JSON Lines logs stay in folders, with only their paths in the database.

## Consequences

- Zero setup and the same behaviour on Windows and macOS; easy to back up or delete.
- API and worker processes both access the file, so use WAL mode and short transactions.
- Not built for many concurrent writers; fine for one job at a time, revisit if that changes.
- Schema changes need migrations from the first release.
