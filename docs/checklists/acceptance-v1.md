# Acceptance test v1 (end to end, by hand)

One run on **Windows** (dev laptop, NVIDIA) and one on the **Mac** (Apple Silicon, 16 GB), with
the real model. About 60–90 minutes per machine, most of it listening.

**Where to record:** copy this file to `docs/acceptance/v1-<windows|mac>-<YYYY-MM-DD>.md`,
fill in every **Result** line and the summary table at the end, and open a PR with it
(`docs: acceptance v1 on <os> LEARNING-204`). Add a comment on
[LEARNING-204](https://lucenenguyen.atlassian.net/browse/LEARNING-204) with the link. Record
clip ids, times and counts only: **no transcript text** (rule from CLAUDE.md).

**You need:** two real clips of ≤ 3 minutes from `$STUTTERCUT_DATA_DIR/clips` (for example
`c001` and one more from `eval/manifest.csv`), one video longer than 3 minutes, DaVinci Resolve
(free), headphones. Optional: Ollama with `qwen3:8b` for the LLM review
([local-llm.md](../guides/local-llm.md)).

---

## A. Setup from scratch

1. Follow [setup-windows.md](../guides/setup-windows.md) or [setup-mac.md](../guides/setup-mac.md)
   in a **new clone** (ASCII-only path), with `pip install -e "backend[dev,asr]"` (Windows with
   NVIDIA: also step 3, CUDA torch).
2. Start from an empty data folder so old jobs do not mix in: in `.env` set
   `STUTTERCUT_HOME=<a new empty folder>` and `STUTTERCUT_DATA_DIR=<your clips folder>`.
3. `python -c "from stuttercut.platform import select_device; print(select_device())"`
4. Start: `./scripts/start.sh` (Mac) or `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`.

**Expected:** pip and npm finish without errors; step 3 prints `mps` (Mac) or `cuda` (Windows
with NVIDIA); the browser opens http://127.0.0.1:8000 on **Upload & jobs**;
http://127.0.0.1:8000/api/health shows `"worker": {"alive": true, ...}` within a few seconds.

**Result:** setup time ____ min · device ____ · issues ____

## B. Upload two real clips (and one that is too long)

1. Drop the **too-long video** on the drop zone.
2. Drop **clip 1**, then **clip 2** right after it (detection options left as they are).
3. Watch the jobs table until both are **Ready for review**.

**Expected:**
- Step 1: an inline red message "`<name>` is m:ss long. Choose a video of 3 minutes or less.";
  no row is added.
- Clip 2 stays **Queued** while clip 1 runs (one job at a time).
- The status line moves through Extracting audio → Making preview → (Loading model) →
  Transcribing · nn% → Detecting cuts (→ Reviewing with LLM if enabled).
- Each clip is ready in under about 1.5 × its length on the Mac (first job: plus the model
  download, about 3 GB, once).
- Each row shows a cut count; Time saved is "—" until you approve cuts.

**Result:** clip 1 ____ (length ____, ready after ____ s, cuts ____) · clip 2 ____ (length
____, ready after ____ s, cuts ____)

## C. Review clip 1

1. Click **Review** on clip 1. Play the preview with **Space**.
2. Click **Approve all sure**.
3. Manual toggles, at least three: **→** to a sure cut and **K** (keep it); **→** to an unsure
   cut and **X** (cut it); click one struck-through word in the transcript to keep it.
4. **One missed cut:** select one or two words in the transcript that should go, pick a
   reason, click **Mark missed cut**.
5. Use the filter chips (Filler, Repeat, Pause, Retake) once each.
6. **Edges:** select a cut whose start clips a syllable or leaves a sound; drag a handle or use
   **Alt+←/→** (start) and **Shift+←/→** (end); click the waveform next to the edge to hear 1 s
   there; **Reset edges** once, then edit again.
7. **Clean preview** (on the Mac: in **Safari**): **Play clean preview** across at least five
   cuts, including a retake; scrub into the middle of a cut; change one decision while it plays.
8. Reload the page (F5 / ⌘R).

**Expected:**
- After step 2 the Sure group shows every sure cut as Cut, and Saved shows time removed.
- Each toggle updates Clean / Saved / Cuts at once.
- The edge editor shows the times to 10 ms; an edited cut says "edited" and is approved.
- Clean preview: no part of a cut is heard (no syllable start before a jump), no click at the
  joins, the picture stays in sync with the voice; scrubbing into a cut continues after it; a
  changed decision is heard right away. Safari: no error, sound starts on the first click.
- The missed cut appears struck through and in the list as "marked by you".
- After the reload every decision and the missed cut are still there.

**Result:** sure approved ____ · toggles ____ · missed cut ok? ____ · edges ok? ____ · clean
preview matches the render? ____ (browser ____) · decisions kept after reload? ____

## D. Render MP4 + XML

1. **Approve & render** (or **Enter**) → **Both** → leave Save to empty (default folder) →
   **Render**.
2. Click **Show in Finder** / **Show in Explorer**.
3. Do C (quickly: Approve all sure is enough) and D for **clip 2**.

**Expected:** the panel shows "Rendered in m:ss" and `<name>_clean.mp4 + <name>_clean.xml`; the
file manager opens with the MP4 selected (default folder Videos/StutterCut, or Movies on the
Mac); the jobs table shows **Rendered**; rendering a 3-minute clip takes ≤ 2 minutes.

**Result:** clip 1 render ____ s, output length ____ · clip 2 render ____ s · encoder (see
Diagnostics → Logs, "render done") ____

## E. Listening check

Run [listening-check.md](listening-check.md) on both MP4s.

**Expected:** every box ticked: no clicks at cuts, no clipped syllables, no meaningful word
removed ("à" used as a real word), lip sync holds, remaining pauses sound natural.

**Result:** clip 1 ____ · clip 2 ____ · timestamps of any problem ____

## F. Open the XML in DaVinci Resolve

1. Resolve → File → Import → Timeline… → choose `<clip 1>_clean.xml`. If asked, point it to
   the original video.
2. Play across a few cuts.

**Expected:** a timeline with one clip per kept segment, cuts at the same places as in the MP4,
total length equal to the MP4 (± 1 frame), sound with every clip.

**Result:** imported? ____ · length ____ vs MP4 ____ · issues ____

## G. Diagnostics

1. Open **Diagnostics**.
2. Pick each job in **Job traces**; filter the logs by **Error** and **Info**.
3. **Export diagnostics (.zip)**; open the zip and search it for a word you know is spoken in
   clip 1.
4. **Open log folder**.

**Expected:** Jobs ≥ 2 with success rate 100% so far; step bars for Extract audio, Preview,
Transcribe, Detect, Render; each trace shows its steps as a waterfall; the zip has `logs/`,
`environment.json`, `metrics.json`, `jobs.json` and **does not contain the spoken word**; the
log folder opens in Finder / Explorer.

**Result:** avg transcribe ____ s · peak memory ____ · word found in zip? ____ (must be no)

## H. Kill the worker in the middle of a job, then retry

1. Upload clip 1 again. While it shows **Transcribing**, kill the worker process:
   - Mac (Terminal): `pkill -9 -f multiprocessing.spawn`
   - Windows (PowerShell):
     `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? CommandLine -match 'spawn_main' | % { Stop-Process -Id $_.ProcessId -Force }`
2. Watch the row, then open http://127.0.0.1:8000/api/health.
3. Click **Retry** on the failed row.

**Expected:** within about 2 s the row shows **Failed at transcribe** with "worker stopped
unexpectedly … Cuts are saved."; `/api/health` shows the worker alive again with
`"restarts": 1`; **View trace** shows the transcribe step in red; Retry runs the job to **Ready
for review**; the earlier rendered jobs and their decisions are unchanged.

**Result:** failed shown after ____ s · restarts ____ · retry ok? ____

## I. Export the reviews and score the detector

In a terminal in the repo (venv active, the same `.env`):

```bash
python -m eval.export_reviews
python -m eval.score_cuts
```

**Expected:** `export_reviews` prints one line per reviewed clip: `<clip_id>: N cuts from job
…`. A clip that already has Audacity labels prints "skipped: … holds other labels"; that is
right, keep those labels. `score_cuts` prints the precision / recall / F1 table and writes
`eval/reports/<today>/cuts_summary.md`.

**Result:** labels written for ____ · F1 overall ____ · recall ____ · review effort per clip
____

---

## Summary (fill in)

| Step | Windows | Mac | Notes |
| --- | --- | --- | --- |
| A. Setup from scratch |  |  |  |
| B. Upload 2 clips + too-long error |  |  |  |
| C. Review (approve sure, toggles, missed cut, edges, clean preview, reload) |  |  |  |
| D. Render MP4 + XML |  |  |  |
| E. Listening check |  |  |  |
| F. XML in DaVinci Resolve |  |  |  |
| G. Diagnostics + export without transcript |  |  |  |
| H. Kill worker mid-job + retry |  |  |  |
| I. export_reviews + score_cuts |  |  |  |

v1 is accepted when every row passes on both machines. Anything that fails becomes a Jira
task under LEARNING-204, with the step letter and the recorded numbers.
