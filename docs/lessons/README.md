# Lessons learned

What we learned while building StutterCut: surprises, mistakes and the fixes that worked. Written **after** doing the work (decisions made **before** go in [`../adr/`](../adr/)).

- One file per lesson: `NNN-short-title.md`, copied from [`TEMPLATE.md`](TEMPLATE.md).
- Keep it to half a page, with evidence (command, numbers, PR link).
- Add a line to the index below.

## Index

| # | Lesson | Jira | Date |
| --- | --- | --- | --- |
| [002](002-crisperwhisper-dual-pass-is-ct2-only.md) | CrisperWhisper one-pass verbatim + intended needs CT2 (no MPS); intended pass made optional | LEARNING-206 | 2026-11-14 |
| [001](001-torch-cuda13-vs-ctranslate2-cuda12.md) | One GPU, two CUDA versions: torch vs CTranslate2 | LEARNING-205 | 2026-11-14 |
