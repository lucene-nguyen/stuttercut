"""Side-by-side transcript pages: python -m eval.compare_html [<report_dir>]

Writes <report_dir>/compare/<clip_id>.html (git-ignored): one column per model, word start
time on hover, fillers (the detector's list: ờ, ừm, [UH], [UM], ...) and immediate repeats
highlighted, and an audio player that seeks to a word when you click it. The player points
at the original clip in $STUTTERCUT_DATA_DIR; nothing is copied. Open the pages locally.
"""

import argparse
import html
import json
from pathlib import Path
from typing import Any

from eval.env import data_dir, newest_report
from eval.ingest import find_media
from eval.score_spike import is_filler, repeat_indices

PAGE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{clip_id} · ASR compare</title>
<style>
:root {{ --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#d2d2d7; --filler:#ffe08a;
  --repeat:#b8dcff; --now:#1d1d1f; --now-fg:#fff; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161617; --fg:#f5f5f7; --muted:#a1a1a6;
  --line:#3a3a3c; --filler:#7a5d00; --repeat:#16466e; --now:#f5f5f7; --now-fg:#161617; }} }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg);
  font:16px/1.7 system-ui, sans-serif; }}
header {{ position:sticky; top:0; background:var(--bg); padding-bottom:8px;
  border-bottom:1px solid var(--line); }}
h1 {{ font-size:18px; margin:0 0 8px; }}
audio {{ width:100%; }}
.legend, .meta {{ color:var(--muted); font-size:13px; }}
.cols {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:16px;
  margin-top:12px; }}
section {{ border:1px solid var(--line); border-radius:8px; padding:12px; }}
h2 {{ font-size:15px; margin:0; }}
.w {{ cursor:pointer; border-radius:3px; padding:0 1px; }}
.w:hover {{ outline:1px solid var(--muted); }}
.f {{ background:var(--filler); }}
.r {{ background:var(--repeat); }}
.now {{ background:var(--now); color:var(--now-fg); }}
mark {{ border-radius:3px; padding:0 4px; color:inherit; }}
</style>
</head>
<body>
<header>
<h1>{clip_id}</h1>
{player}
<div class="legend"><mark class="f">filler</mark> <mark class="r">repeat (earlier copy)</mark>
· hover a word for its start time · click to play from it</div>
</header>
<div class="cols">
{columns}
</div>
<script>
const audio = document.querySelector("audio");
const words = [...document.querySelectorAll(".w")];
document.addEventListener("click", (e) => {{
  const w = e.target.closest(".w");
  if (!w || !audio) return;
  audio.currentTime = +w.dataset.s;
  audio.play();
}});
if (audio) audio.addEventListener("timeupdate", () => {{
  const t = audio.currentTime;
  for (const w of words) w.classList.toggle("now", +w.dataset.s <= t && t < +w.dataset.e);
}});
</script>
</body>
</html>
"""


def column(model: str, result: dict[str, Any] | None) -> str:
    if result is None:
        return f"<section><h2>{html.escape(model)}</h2><p class='meta'>no result</p></section>"
    words = result["words"]
    repeats = repeat_indices(words)
    spans = []
    for i, w in enumerate(words):
        cls = "w" + (" f" if is_filler(w["word"]) else "") + (" r" if i in repeats else "")
        spans.append(
            f'<span class="{cls}" data-s="{w["start"]:.2f}" data-e="{w["end"]:.2f}" '
            f'title="{w["start"]:.2f} s">{html.escape(w["word"])}</span>'
        )
    meta = (
        f"{html.escape(str(result['model_id']))} · {result['device']} · {len(words)} words · "
        f"RTF {result['rtf']} · peak RSS {result['peak_rss_mb']:.0f} MB"
    )
    return (
        f"<section><h2>{html.escape(model)}</h2><div class='meta'>{meta}</div>"
        f"<p>{' '.join(spans)}</p></section>"
    )


def build_page(clip_id: str, results: dict[str, dict[str, Any] | None], audio: str | None) -> str:
    player = (
        f'<audio controls preload="metadata" src="{html.escape(audio)}"></audio>'
        if audio
        else "<p class='meta'>audio not found (set STUTTERCUT_DATA_DIR)</p>"
    )
    columns = "\n".join(column(m, r) for m, r in results.items())
    return PAGE.format(clip_id=html.escape(clip_id), player=player, columns=columns)


def write_pages(report_dir: Path, root: Path | None, only: list[str] | None = None) -> list[Path]:
    models = sorted(
        p
        for p in report_dir.iterdir()
        if p.is_dir() and any(p.glob("*.json")) and (only is None or p.name in only)
    )
    clip_ids = sorted({f.stem for m in models for f in m.glob("*.json")})
    out_dir = report_dir / "compare"
    out_dir.mkdir(exist_ok=True)
    pages = []
    for clip_id in clip_ids:
        results = {}
        for m in models:
            f = m / f"{clip_id}.json"
            results[m.name] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        try:
            audio = find_media(root, clip_id).as_uri() if root else None
        except FileNotFoundError:
            audio = None
        page = out_dir / f"{clip_id}.html"
        page.write_text(build_page(clip_id, results, audio), encoding="utf-8")
        pages.append(page)
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report_dir", type=Path, nargs="?", help="default: newest report")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--models", nargs="+", help="model folders to show (default: all)")
    args = parser.parse_args()
    try:
        root: Path | None = data_dir(args.data_dir)
    except SystemExit as e:
        print(f"{e}; pages will have no audio player")
        root = None
    for page in write_pages(args.report_dir or newest_report(), root, args.models):
        print(page.resolve().as_uri())


if __name__ == "__main__":
    main()
