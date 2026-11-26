# LEARNING-233 — Cross-platform setup and start scripts

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-233

## Prompt

Part of the batch prompt for LEARNING-204 (2026-11-26): one branch + PR per task, merge when CI is green.

```text
LEARNING-233 Cross-platform: setup-mac.md and setup-windows.md complete and verified on Windows; a one-command start script for each OS (backend + frontend); CI already covers 3 OSes — add a smoke run of the CLI with the fake transcriber on macos.
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/11 (merged 2026-11-27, squash `3c23a5a`).

**Worked well**
- Serving the built UI from the API made "one command" one process and one port; Vite stays for UI work.
- macOS CI now runs the CLI (fake transcriber, real render: it picked `h264_videotoolbox`) and `start.sh`.

**Had to be corrected or deviated from the prompt**
- Verifying from scratch in a folder named with Vietnamese letters showed Python 3.11 cannot import an editable install there (`.pth` read as cp1252, lesson 005). The scripts set `PYTHONPATH`; the guide asks for an ASCII checkout path.

**Next time**
- Verify setup guides in a path with a space and a non-ASCII letter.
