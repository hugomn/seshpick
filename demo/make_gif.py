#!/usr/bin/env python3
"""Render demo/seshpick.gif from captured terminal frames (plain text, one file per frame).

The README demo is recorded against demo/registry.json (SESHPICK_DEMO_REGISTRY), never against real
sessions. Frames are captured from the real picker; this script only draws them. Needs Pillow.

    python3 demo/make_gif.py FRAMES_DIR demo/seshpick.gif
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

COLS, ROWS, PX = 96, 22, 15
BG, FG, DIM, ACCENT, HILITE, GREEN = "#0d1117", "#e6edf3", "#8b949e", "#79c0ff", "#1c2a3a", "#56d364"
FONT_CANDIDATES = ["JetBrainsMonoNL-Medium.ttf", "JetBrainsMono-Regular.ttf", "/System/Library/Fonts/Menlo.ttc",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]

def font():
    for name in FONT_CANDIDATES:
        for p in (Path(name), Path.home() / "Library/Fonts" / name):
            if p.is_file():
                return ImageFont.truetype(str(p), PX)
    return ImageFont.load_default()

def lines_of(path):
    text = Path(path).read_text().rstrip("\n").split("\n")
    while text and not text[0].strip():
        text.pop(0)
    return [l[:COLS] for l in text][:ROWS]

def frame(lines, fnt, cw, lh, pad=14, highlight_first_result=True):
    img = Image.new("RGB", (COLS * cw + 2 * pad, ROWS * lh + 2 * pad), BG)
    d = ImageDraw.Draw(img)
    seen_result = False
    for i, line in enumerate(lines):
        y = pad + i * lh
        color = FG
        if line.startswith("session>"):
            d.text((pad, y), "session>", font=fnt, fill=ACCENT)
            d.text((pad + 8 * cw, y), line[8:], font=fnt, fill=FG)
            continue
        if line.lstrip().startswith(("enter:", "$ ")) or "──" in line:
            color = ACCENT if line.startswith("$ ") else DIM
        elif line.startswith(("▌", "  ")) and highlight_first_result and not seen_result and "──" not in line and "enter:" not in line:
            seen_result = True
            d.rectangle([pad - 6, y - 1, pad + COLS * cw, y + lh - 2], fill=HILITE)
        if "running" in line and line.startswith(("▌", "  ")):
            k = line.index("running")
            d.text((pad, y), line[:k], font=fnt, fill=color)
            d.text((pad + k * cw, y), "running", font=fnt, fill=GREEN)
            continue
        d.text((pad, y), line, font=fnt, fill=color)
    return img

def main(src, out):
    fnt = font()
    cw = int(round(fnt.getlength("M"))) or 9
    lh = PX + 5
    steps = [  # (frame file or literal lines, seconds)
        (["~/work/lumen $ seshpick"], 1.0),
        ("01-list.txt", 1.8), ("02-t.txt", 0.6), ("03-tr.txt", 0.6), ("04-tri.txt", 1.8), ("05-open.txt", 2.2),
        (["~/work/lumen $ seshpick orbit"], 1.0),
        ("06-orbit.txt", 1.6), ("07-fork.txt", 2.4),
    ]
    frames, durations = [], []
    for spec, secs in steps:
        lines = spec if isinstance(spec, list) else lines_of(Path(src) / spec)
        img = frame(lines, fnt, cw, lh, highlight_first_result=not isinstance(spec, list))
        frames.append(img.convert("P", palette=Image.ADAPTIVE, colors=16))
        durations.append(int(secs * 1000))
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"{out}: {len(frames)} frames, {sum(durations) / 1000:.1f} s, {Path(out).stat().st_size // 1024} KB, {frames[0].size[0]}x{frames[0].size[1]}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
