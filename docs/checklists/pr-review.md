# PR review checklist

- [ ] PR title and commits carry the Jira key (`LEARNING-xxx`)
- [ ] Scope matches the Jira task; nothing unrelated
- [ ] Follows the design docs; any deviation explained (or a new ADR)
- [ ] CI green on Ubuntu, Windows and macOS
- [ ] New logic has tests; bug fixes start with a failing test
- [ ] No hard-coded paths, device or encoder; thresholds in config
- [ ] No audio/video or secrets leave the machine; `.env.example` updated if needed
- [ ] Errors set a clear job state, a span and a log line with the job id
- [ ] README / CLAUDE.md / docs updated if behaviour or commands changed
- [ ] A lesson in `docs/lessons/` if something surprising was learned
