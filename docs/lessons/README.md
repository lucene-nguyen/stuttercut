# Lessons learned

What we learned while building StutterCut: surprises, mistakes and the fixes that worked. Written **after** doing the work (decisions made **before** go in [`../adr/`](../adr/)).

- One file per lesson: `NNN-short-title.md`, copied from [`TEMPLATE.md`](TEMPLATE.md).
- Keep it to half a page, with evidence (command, numbers, PR link).
- Add a line to the index below.

## Index

| # | Lesson | Jira | Date |
| --- | --- | --- | --- |
| [006](006-merge-before-padding-pad-into-silence.md) | Merge before padding; pad into silence; nearest frame, at least one frame per cut | LEARNING-209 | 2026-11-27 |
| [005](005-python-311-pth-files-are-not-utf8-on-windows.md) | Python 3.11 reads .pth files as cp1252 on Windows: a non-ASCII checkout path breaks `pip install -e` | LEARNING-233 | 2026-11-27 |
| [004](004-windows-locks-a-file-just-written.md) | Windows locks a file just written (retry rename/delete); snap cuts to frames for A/V sync | LEARNING-210 | 2026-11-15 |
| [003](003-check-what-the-model-really-writes.md) | Check what the model really writes ([UH]/[UM]), and what else shares the machine | LEARNING-207 | 2026-11-14 |
| [002](002-crisperwhisper-dual-pass-is-ct2-only.md) | CrisperWhisper one-pass verbatim + intended needs CT2 (no MPS); intended pass made optional | LEARNING-206 | 2026-11-14 |
| [001](001-torch-cuda13-vs-ctranslate2-cuda12.md) | One GPU, two CUDA versions: torch vs CTranslate2 | LEARNING-205 | 2026-11-14 |
