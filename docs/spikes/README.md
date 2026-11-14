# Spikes

Time-boxed experiments that answer one question with data before we build on it. A spike ends with a decision, usually recorded as an ADR in [`../adr/`](../adr/).

- One file per spike: `YYYY-MM-short-title.md`, copied from [`TEMPLATE.md`](TEMPLATE.md).
- Raw outputs (reports, CSVs) go to `eval/reports/` or `perf/`, linked from the spike file.

## Index

| Spike | Question | Decision | Jira |
| --- | --- | --- | --- |
| [2026-11-asr-models](2026-11-asr-models.md) | Which ASR model keeps Vietnamese stutters with accurate word timestamps? | CrisperWhisper 2.0 large verbatim + verbatim/intended diff + VAD + pause rules; PhoWhisper dropped ([ADR 0002](../adr/0002-crisperwhisper-verbatim-asr.md)) | [LEARNING-205](https://lucenenguyen.atlassian.net/browse/LEARNING-205) |
