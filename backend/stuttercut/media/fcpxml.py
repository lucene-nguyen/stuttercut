"""FCP7 XML (xmeml v5) timeline of the keep-segments, for DaVinci Resolve / Premiere (LEARNING-210).

One video and one audio clipitem per keep-segment, all referencing the original file: nothing is
re-encoded, and the editor can still open up any cut. Times are whole frames of the source rate
(keep-segments are already snapped to that grid by ``render.plan``).
"""

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path

from stuttercut.media.render import Segment, VideoInfo, discard, move_into_place


def _rate(parent: ET.Element, fps: Fraction) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(round(fps))
    ET.SubElement(rate, "ntsc").text = "TRUE" if fps.denominator == 1001 else "FALSE"


def _text(parent: ET.Element, tag: str, value: object) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = str(value)
    return el


def path_url(path: Path) -> str:
    """file://localhost/... with percent-encoding (spaces, Vietnamese), as editors expect."""
    return "file://localhost" + path.resolve().as_uri().removeprefix("file://")


def timeline(source: Path, keeps: Sequence[Segment], info: VideoInfo, name: str) -> ET.Element:
    fps = info.fps
    frames = [(round(s * fps), round(e * fps)) for s, e in keeps]
    total = sum(b - a for a, b in frames)
    src_frames = round(info.duration_s * fps)

    root = ET.Element("xmeml", version="5")
    seq = ET.SubElement(root, "sequence", id="sequence-1")
    _text(seq, "name", name)
    _text(seq, "duration", total)
    _rate(seq, fps)
    media = ET.SubElement(seq, "media")
    video = ET.SubElement(media, "video")
    chars = ET.SubElement(ET.SubElement(video, "format"), "samplecharacteristics")
    _rate(chars, fps)
    _text(chars, "width", info.width)
    _text(chars, "height", info.height)
    tracks = {"video": ET.SubElement(video, "track")}
    if info.has_audio:
        tracks["audio"] = ET.SubElement(ET.SubElement(media, "audio"), "track")

    t = 0
    for i, (a, b) in enumerate(frames, start=1):
        for kind, track in tracks.items():
            item = ET.SubElement(track, "clipitem", id=f"clipitem-{kind[0]}{i}")
            _text(item, "name", source.name)
            _text(item, "enabled", "TRUE")
            _text(item, "duration", src_frames)
            _rate(item, fps)
            _text(item, "start", t)
            _text(item, "end", t + b - a)
            _text(item, "in", a)
            _text(item, "out", b)
            if i == 1 and kind == "video":  # full file definition once, then by id
                f = ET.SubElement(item, "file", id="file-1")
                _text(f, "name", source.name)
                _text(f, "pathurl", path_url(source))
                _rate(f, fps)
                _text(f, "duration", src_frames)
                fmedia = ET.SubElement(f, "media")
                v = ET.SubElement(ET.SubElement(fmedia, "video"), "samplecharacteristics")
                _text(v, "width", info.width)
                _text(v, "height", info.height)
                if info.has_audio:
                    ET.SubElement(fmedia, "audio")
            else:
                ET.SubElement(item, "file", id="file-1")
            if kind == "audio":
                src = ET.SubElement(item, "sourcetrack")
                _text(src, "mediatype", "audio")
                _text(src, "trackindex", 1)
        t += b - a
    return root


def write_xml(source: Path, keeps: Sequence[Segment], info: VideoInfo, out_dir: Path) -> Path:
    """out_dir/<stem>_clean.xml (or _clean_2 ...): never overwrites; temp file + rename."""
    root = timeline(source, keeps, info, f"{source.stem}_clean")
    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    tmp = out_dir / f".{source.stem}_clean.part.xml"
    try:
        header = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
        tmp.write_text(f"{header}{body}\n", encoding="utf-8")
        return move_into_place(tmp, out_dir, source.stem, ".xml")
    finally:
        discard(tmp)
