# LEARNING-234 — Repository foundations

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-234

## Prompt

```text
Task: LEARNING-234 — set up the repository foundations. Read CLAUDE.md and docs/README.md first.

Create branch feature/LEARNING-234-repo-foundations and scaffold:

1. Layout exactly as in CLAUDE.md "Repository layout" (empty packages with __init__.py; keep existing docs/ content).
2. Backend: backend/pyproject.toml (Python 3.11+, package "stuttercut"), dev extras: ruff, mypy, pytest, hypothesis, pre-commit. Configure ruff (lint + format) and mypy (strict for backend/stuttercut).
3. A minimal FastAPI app with GET /api/health returning {"status": "ok"} and one pytest test for it.
4. Frontend: Vite + React + TypeScript strict, ESLint + Prettier, vitest with one sample test; src/features/{upload,review,diagnostics}.
5. .pre-commit-config.yaml running ruff, ruff-format, mypy and basic hygiene hooks.
6. GitHub Actions ci.yml: on PR and push to main, matrix ubuntu-latest / windows-latest / macos-latest; backend lint + types + pytest; frontend lint + vitest on ubuntu only.
7. .gitignore for Python, Node, venvs, .env, model caches, media outputs, eval/clips/, and .qodo/. Add .env.example (LLM_API_KEY=).
8. README.md: what the project is, setup and run commands, links to CLAUDE.md and docs/README.md.
9. docs/adr/0001-local-first-architecture.md, 0002-crisperwhisper-verbatim-asr.md (status: proposed, pending LEARNING-205), 0003-worker-process-and-watchdog.md, 0004-sqlite-for-state-and-traces.md — short ADRs (context, decision, consequences).
10. Update the "Common commands" section of CLAUDE.md so every command really works.

Run lint, type check and all tests locally; fix until green. Commit in small Conventional Commits with "LEARNING-234" in each message, push the branch and open a PR to main using .github/pull_request_template.md. Do not add application logic beyond the health endpoint.
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/1 (squash-merged 2026-11-14)

**Worked well**
- CI green on the first run on ubuntu, windows and macos (run 43576958847).
- Layout, ADRs 0001–0004, pre-commit and README landed as asked; every commit carried the Jira key.

**Had to be corrected or deviated from the prompt**
- Repo had no commits, so a PR had no base: one docs-only commit went to `main` first.
- Tool config moved to a root `pyproject.toml` (ruff/mypy/pytest run from the root); the package stays in `backend/pyproject.toml`.
- Added `.gitattributes` forcing LF, because git on Windows converted to CRLF and broke the formatters.
- Review follow-ups: `npm run build` in CI, `tests/media/README.md` (synthetic clips generated at test time).
- `gh` was not installed, so the PR had to be opened by hand; the CLAUDE.md workflow now uses `gh pr create` + `gh pr checks --watch`.

**Next time**
- Check that `gh` is installed and authenticated before a task that ends in a PR.
- Do not let the agent install packages with look-alike names (it tried `httpx2`; blocked).
