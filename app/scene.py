# -*- coding: utf-8 -*-
"""根据 seed_data 生成同比例、同朝向的壁画样片 SVG。

每张样片是同一幅“全局壁画”上的一个 480x360 取景窗（原点 ox,oy），
因此同一处纹样在两张样片上的局部坐标差，恰好等于取景原点之差。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .seed_data import IMAGES, CRACKS, MOTIFS, IMG_W, IMG_H, MASTER_W, MASTER_H

SAMPLE_DIR = Path(__file__).resolve().parent / "static" / "samples"

_PLASTER = "#ecd9b0"
_INK = "#43342a"


def _lotus(x: float, y: float, r: float, color: str) -> str:
    petals = []
    for k in range(8):
        import math
        ang = k * math.pi / 4
        cx = x + math.cos(ang) * r * 0.62
        cy = y + math.sin(ang) * r * 0.62
        petals.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r * 0.42:.1f}" '
            f'fill="{color}" opacity="0.85"/>'
        )
    return (
        f'<g>'
        + "".join(petals)
        + f'<circle cx="{x}" cy="{y}" r="{r * 0.72:.1f}" fill="#e8c27a" '
        f'stroke="{_INK}" stroke-width="1.6"/>'
        f'<circle cx="{x}" cy="{y}" r="{r * 0.34:.1f}" fill="{color}" '
        f'stroke="{_INK}" stroke-width="1.4"/>'
        f'<circle cx="{x}" cy="{y}" r="2.4" fill="{_INK}"/>'
        f"</g>"
    )


def _diamond(x: float, y: float, r: float, color: str) -> str:
    return (
        f'<g stroke="{_INK}" stroke-width="1.6">'
        f'<polygon points="{x},{y - r} {x + r},{y} {x},{y + r} {x - r},{y}" '
        f'fill="{color}" opacity="0.88"/>'
        f'<polygon points="{x},{y - r * 0.5} {x + r * 0.5},{y} '
        f'{x},{y + r * 0.5} {x - r * 0.5},{y}" fill="#e8c27a"/>'
        f'<circle cx="{x}" cy="{y}" r="3" fill="{_INK}"/>'
        f"</g>"
    )


def _spiral(x: float, y: float, r: float, color: str) -> str:
    return (
        f'<g fill="none" stroke-linecap="round">'
        f'<circle cx="{x}" cy="{y}" r="{r}" stroke="{color}" stroke-width="5" opacity="0.8"/>'
        f'<path d="M {x} {y} '
        f"m 0 {-r * 0.55:.0f} "
        f"a {r * 0.55:.0f} {r * 0.55:.0f} 0 1 1 {-r * 0.4:.0f} {r * 0.15:.0f} "
        f'a {r * 0.32:.0f} {r * 0.32:.0f} 0 1 0 {r * 0.22:.0f} {r * 0.22:.0f}" '
        f'stroke="{_INK}" stroke-width="2.4"/>'
        f'<circle cx="{x}" cy="{y}" r="3" fill="{_INK}"/>'
        f"</g>"
    )


def _motif(m: dict) -> str:
    if m["kind"] == "lotus":
        return _lotus(m["x"], m["y"], m["r"], m["color"])
    if m["kind"] == "diamond":
        return _diamond(m["x"], m["y"], m["r"], m["color"])
    return _spiral(m["x"], m["y"], m["r"], m["color"])


def _crack_path(x: float, y: float, seed: int) -> str:
    """以 (x,y) 为中点的确定性锯齿裂缝。"""
    s = seed * 37 + 11

    def jitter(k: int) -> float:
        return ((s * (k + 3) * 17) % 13) - 6

    pts = [
        (x - 46, y - 22 + jitter(0)),
        (x - 26, y - 10 + jitter(1)),
        (x - 12, y - 16 + jitter(2)),
        (x + 2, y + jitter(3)),
        (x + 16, y + 12 + jitter(4)),
        (x + 30, y + 6 + jitter(5)),
        (x + 46, y + 24 + jitter(6)),
    ]
    d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    branch = (
        f"M {x + 2:.1f},{y:.1f} l {10 + (seed % 5)},{ -16 - (seed % 4)} "
        f"M {x - 12:.1f},{y - 16:.1f} l {-12 - (seed % 3)},{-10 - (seed % 5)}"
    )
    return (
        f'<path d="{d}" fill="none" stroke="#2c2620" stroke-width="2.6" '
        f'stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>'
        f'<path d="{branch}" fill="none" stroke="#2c2620" stroke-width="1.6" '
        f'stroke-linecap="round" opacity="0.8"/>'
    )


def render_sample_svg(image: dict, cracks: List[dict]) -> str:
    ox, oy = image["ox"], image["oy"]
    clip_id = f"clip-{image['id']}"
    motif_svg = "\n".join(_motif(m) for m in MOTIFS)
    crack_svg = "\n".join(
        _crack_path(c["x"], c["y"], idx + 1)
        for idx, c in enumerate(cracks)
        if c["image_id"] == image["id"]
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{IMG_W}" height="{IMG_H}"
     viewBox="0 0 {IMG_W} {IMG_H}" role="img"
     aria-label="{image['name']}">
  <defs>
    <clipPath id="{clip_id}">
      <rect x="0" y="0" width="{IMG_W}" height="{IMG_H}"/>
    </clipPath>
    <pattern id="grain-{image['id']}" width="26" height="26" patternUnits="userSpaceOnUse">
      <circle cx="4" cy="6" r="0.9" fill="#b89a63" opacity="0.35"/>
      <circle cx="18" cy="16" r="0.8" fill="#a98a55" opacity="0.3"/>
      <circle cx="11" cy="23" r="0.7" fill="#c4a871" opacity="0.4"/>
    </pattern>
  </defs>

  <rect x="0" y="0" width="{IMG_W}" height="{IMG_H}" fill="{_PLASTER}"/>
  <g clip-path="url(#{clip_id})">
    <!-- 同一幅全局壁画，按取景原点平移 -->
    <g transform="translate({-ox},{-oy})">
      <rect x="0" y="0" width="{MASTER_W}" height="{MASTER_H}" fill="{_PLASTER}"/>
      <rect x="0" y="26" width="{MASTER_W}" height="18" fill="#7a4a2b" opacity="0.55"/>
      <rect x="0" y="{MASTER_H - 44}" width="{MASTER_W}" height="18"
            fill="#2b5d8a" opacity="0.45"/>
      <rect x="0" y="44" width="{MASTER_W}" height="4" fill="#c8862d" opacity="0.8"/>
      <rect x="0" y="{MASTER_H - 26}" width="{MASTER_W}" height="4"
            fill="#c8862d" opacity="0.8"/>
      {motif_svg}
    </g>
    <rect x="0" y="0" width="{IMG_W}" height="{IMG_H}"
          fill="url(#grain-{image['id']})"/>
    {crack_svg}
  </g>

  <rect x="2.5" y="2.5" width="{IMG_W - 5}" height="{IMG_H - 5}"
        fill="none" stroke="#6e542c" stroke-width="5"/>
  <rect x="7" y="7" width="{IMG_W - 14}" height="{IMG_H - 14}"
        fill="none" stroke="#f3e4c2" stroke-width="1.4" opacity="0.8"/>
</svg>
"""


def ensure_sample_files() -> List[Path]:
    """缺少样片 SVG 时按内置数据生成；返回文件路径列表。"""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for img in IMAGES:
        path = SAMPLE_DIR / f"{img['id']}.svg"
        if not path.exists():
            path.write_text(
                render_sample_svg(img, CRACKS), encoding="utf-8"
            )
            written.append(path)
    return written


def generate_all(force: bool = True) -> List[Path]:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for img in IMAGES:
        path = SAMPLE_DIR / f"{img['id']}.svg"
        if force or not path.exists():
            path.write_text(render_sample_svg(img, CRACKS), encoding="utf-8")
        paths.append(path)
    return paths


if __name__ == "__main__":
    paths = generate_all(force=True)
    for p in paths:
        print("generated", p)
