# StutterCut documentation

Index of every project document. Design decisions live in these documents; code follows them.

## Design and planning

| Document | What it covers | Link |
| --- | --- | --- |
| Architecture & System Design | Components, data model, API design, job state machine, sequence diagrams, non-functional design, key decisions and risks | https://claude.ai/artifact/VS1e7fn8nBuXpN9RofBWog |
| Test Plan & Methodology | Quality goals, test levels, accuracy evaluation, performance and fault-injection tests, CI matrix, test data, phase gates | https://claude.ai/artifact/84bcjNJbxJhGFN1PXmUnE8 |
| UI design | 3 screens: Upload & jobs, Review & render, Diagnostics (interactive prototype) | https://claude.ai/artifact/R8mrccDqYyksePiRgtTdk3 |
| Architecture board | Pipeline overview and cross-cutting concerns (whiteboard) | https://claude.ai/artifact/9XFCtLfjpENKQEhRmdggSC |

> The documents above are hosted on claude.ai and may be private. If a link does not open, ask the project owner for access.

## Diagrams in this repo

| File | Diagram | Open with |
| --- | --- | --- |
| [`diagrams/stuttercut-architecture.drawio`](diagrams/stuttercut-architecture.drawio) | Container architecture with technology icons | draw.io / app.diagrams.net |
| [`diagrams/seq-1-upload-processing.mmd`](diagrams/seq-1-upload-processing.mmd) | Sequence: upload and processing | Mermaid source: mermaid.live, or draw.io Arrange > Insert > Advanced > Mermaid |
| [`diagrams/seq-2-review-render.mmd`](diagrams/seq-2-review-render.mmd) | Sequence: review, approve and render | Mermaid |
| [`diagrams/seq-3-failure-retry.mmd`](diagrams/seq-3-failure-retry.mmd) | Sequence: failure, watchdog and retry | Mermaid |

## Project tracking (Jira)

Epic: [LEARNING-204](https://lucenenguyen.atlassian.net/browse/LEARNING-204) — Stutter Cut Tool

| Key | Task |
| --- | --- |
| [LEARNING-205](https://lucenenguyen.atlassian.net/browse/LEARNING-205) | Spike: evaluate verbatim ASR models on Vietnamese stuttered clips |
| [LEARNING-206](https://lucenenguyen.atlassian.net/browse/LEARNING-206) | Python worker: audio extraction and transcription with word timestamps |
| [LEARNING-207](https://lucenenguyen.atlassian.net/browse/LEARNING-207) | Disfluency detection rule engine |
| [LEARNING-208](https://lucenenguyen.atlassian.net/browse/LEARNING-208) | Flag retakes and false starts with an LLM API |
| [LEARNING-209](https://lucenenguyen.atlassian.net/browse/LEARNING-209) | React UI: Upload & jobs, Review & render |
| [LEARNING-210](https://lucenenguyen.atlassian.net/browse/LEARNING-210) | Render with FFmpeg and export FCP XML |
| [LEARNING-228](https://lucenenguyen.atlassian.net/browse/LEARNING-228) | Structured logging, per-job tracing and metrics |
| [LEARNING-229](https://lucenenguyen.atlassian.net/browse/LEARNING-229) | Diagnostics screen: metrics, traces, logs |
| [LEARNING-233](https://lucenenguyen.atlassian.net/browse/LEARNING-233) | Cross-platform support: develop on Windows, run on Mac |
| [LEARNING-234](https://lucenenguyen.atlassian.net/browse/LEARNING-234) | Engineering standards: lint, tests, CI, conventions, docs |
| [LEARNING-235](https://lucenenguyen.atlassian.net/browse/LEARNING-235) | Resource limits and watchdog |

## In-repo docs

| Folder / file | Purpose |
| --- | --- |
| [`../CLAUDE.md`](../CLAUDE.md) | Guidance for Claude Code working in this repo |
| [`adr/`](adr/) | Architecture Decision Records: decisions made before the work |
| [`lessons/`](lessons/) | Lessons learned after the work (template inside) |
| [`spikes/`](spikes/) | Time-boxed experiments with data (template inside) |
| [`guides/`](guides/) | Step-by-step how-tos: setup, labelling, eval |
| [`prompts/`](prompts/) | Prompts given to Claude Code, one per Jira task |
| [`checklists/`](checklists/) | PR review, release, listening check |
| [`diagrams/`](diagrams/) | draw.io and Mermaid sources |
| [`../.github/pull_request_template.md`](../.github/pull_request_template.md) | PR template |
