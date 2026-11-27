# 006 — Merge before padding; pad into silence

Date: 2026-11-27 · Jira: LEARNING-209 · PR: #13

## Context
The render plan (`media.render.plan`) turns approved cuts into keep-segments. Since LEARNING-210 it
shrank every cut by 40 ms on both sides (to protect a neighbouring syllable), then merged cuts
closer than 50 ms, then snapped the keep-segments outward to whole frames.

## What went wrong / surprised me
A review simulated the plan at 30 fps and found three bugs:
1. Touching cuts did not merge: `(1.0, 1.3), (1.3, 1.6), (1.65, 2.0)` left the scraps
   `(1.233, 1.367)` and `(1.533, 1.7)` in the video, because each cut was shrunk before merging.
2. Short cuts vanished: a 70 ms or 120 ms cut lost 2 x 40 ms, then the outward snap of the keeps
   closed what was left. Detected and approved, but not cut.
3. Pause cuts got 40 ms of padding on top of the 150 ms the pause rule already keeps.

All three passed the old tests, which checked each rule alone, not their order.

## What I learned
Order matters more than each rule:
1. **Group first**, then pad only the group's outer edges. A gap of under 150 ms with no word in
   it is silence; merge it.
2. **Pad into silence** when there is room (the neighbour stays at least the padding away and the
   cut word goes fully); pad inward only when a word touches, and never below 60 ms.
3. **Nearest frame**, plus "at least one frame" for tiny cuts. Outward snapping of the keeps
   always favoured keeping, which silently undid short cuts.
4. Edges the user or a rule already placed (edited, pause) get no padding.

## Evidence
- `tests/unit/test_render_plan.py`: the repro now gives one cut `(1.033, 1.967)`; 30/70/120/200 ms
  cuts are all cut; hypothesis properties: no keep inside a mergeable gap, every cut removes at
  least one frame, no kept word loses more than one frame.
- `tests/integration/test_render.py`: three touching cuts render as one, duration = plan ± 1 frame.

## Next time
Test a pipeline of geometry rules with properties over generated timelines (words and cuts), not
one rule at a time; and write down the order of the rules where they are defined.
