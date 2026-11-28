"""生成 ScoutMind FM27 品牌视觉资源。

单一几何定义（256 × 256 viewBox）同时导出：
  - SVG：浅色背景主标识、深色背景主标识、单色标识、应用图标；
  - PNG：透明背景主标识、透明背景应用图标（64–1024）；
  - Windows ICO：16 / 32 / 48 / 64 / 128 / 256（小尺寸使用 32 位 BMP，256 使用 PNG）；
  - Favicon：favicon.svg / favicon.png / favicon.ico；
  - Electron 构建资源：desktop/build/icon.png 与 desktop/build/icon.ico。

所有形状都由同一组坐标推导，禁止手工修改单独尺寸的图形。
用法：python tools/brand/generate_brand_assets.py
"""

from __future__ import annotations

import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

VIEW = 256
STROKE = 22
NODE = (128, 132, 7)

# 经典几何 S：顶横 → 左半圆 → 中横 → 右半圆 → 底横。
S_PATH = "M174 64H108A34 34 0 0 0 108 132H148A34 34 0 0 1 148 200H82"
S_ARC_LEFT = (108, 98, 34)  # cx, cy, r
S_ARC_RIGHT = (148, 166, 34)

NAVY = "#0B1B33"
BRAND_BLUE = "#2563EB"
CYAN = "#22D3EE"
LIGHT_MARK = "#1E3A8A"
MONO = "#172334"
WHITE = "#FFFFFF"

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_BRAND = ROOT / "frontend" / "public" / "brand"
PUBLIC_ROOT = ROOT / "frontend" / "public"
DESKTOP_BUILD = ROOT / "desktop" / "build"


def _svg_mark(color: str, node: str | None, title: str) -> str:
    node_markup = f'\n  <circle cx="{NODE[0]}" cy="{NODE[1]}" r="{NODE[2]}" fill="{node}" />' if node else ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" '
        f'aria-label="{title}">\n'
        f'  <title>{title}</title>\n'
        f'  <path d="{S_PATH}" fill="none" stroke="{color}" stroke-width="{STROKE}" '
        'stroke-linecap="round" stroke-linejoin="round" />'
        f"{node_markup}\n"
        "</svg>\n"
    )


def _svg_app_icon() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" '
        'aria-label="ScoutMind FM27 应用图标">\n'
        "  <title>ScoutMind FM27</title>\n"
        f'  <rect width="256" height="256" rx="54" fill="{NAVY}" />\n'
        '  <rect x="7" y="7" width="242" height="242" rx="47" fill="none" stroke="#FFFFFF" '
        'stroke-opacity="0.12" stroke-width="2" />\n'
        f'  <path d="{S_PATH}" fill="none" stroke="{WHITE}" stroke-width="{STROKE}" '
        'stroke-linecap="round" stroke-linejoin="round" />\n'
        f'  <circle cx="{NODE[0]}" cy="{NODE[1]}" r="{NODE[2]}" fill="{CYAN}" />\n'
        "</svg>\n"
    )


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _paint(size: int, *, tile: bool, stroke: str, node: str | None) -> Image.Image:
    """按统一几何绘制一张 RGBA 图；先超采样再缩放，避免小尺寸发虚。"""
    scale = 8 if size <= 64 else 4 if size <= 256 else 2
    edge = size * scale
    image = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    unit = edge / VIEW

    def point(x: float, y: float) -> tuple[float, float]:
        return (x * unit, y * unit)

    if tile:
        draw.rounded_rectangle([0, 0, edge - 1, edge - 1], radius=54 * unit, fill=(*_hex(NAVY), 255))
        draw.rounded_rectangle(
            [10 * unit, 10 * unit, 246 * unit, 246 * unit],
            radius=44 * unit,
            outline=(255, 255, 255, 22),
            width=max(1, round(2 * unit)),
        )

    # 用密集采样还原 SVG 路径：SVG 的描边以路径为中心，Pillow 的 arc 则向内收缩，
    # 因此这里按中心线连续盖上圆形笔刷，天然得到圆角端点与平滑连接。
    centerline: list[tuple[float, float]] = []

    def add_segment(x1: float, y1: float, x2: float, y2: float) -> None:
        steps = max(2, int(math.hypot(x2 - x1, y2 - y1) / 2))
        for step in range(steps + 1):
            ratio = step / steps
            centerline.append(point(x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio))

    add_segment(174, 64, 108, 64)
    left_x, left_y, radius_px = S_ARC_LEFT
    for step in range(1, 91):
        angle = math.radians(-90 - step * 2)
        centerline.append(point(left_x + radius_px * math.cos(angle), left_y + radius_px * math.sin(angle)))
    add_segment(108, 132, 148, 132)
    right_x, right_y, _ = S_ARC_RIGHT
    for step in range(1, 91):
        angle = math.radians(-90 + step * 2)
        centerline.append(point(right_x + radius_px * math.cos(angle), right_y + radius_px * math.sin(angle)))
    add_segment(148, 200, 82, 200)

    radius = (STROKE / 2) * unit
    color = (*_hex(stroke), 255)
    for cx, cy in centerline:
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)

    if node:
        cx, cy = point(NODE[0], NODE[1])
        radius = NODE[2] * unit
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(*_hex(node), 255))

    return image.resize((size, size), Image.LANCZOS)


def _png(image: Image.Image, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=True)


def _icon_entry(image: Image.Image, size: int) -> bytes:
    """256 使用 PNG 压缩，小尺寸使用 32 位 BMP（兼容旧版 Windows Shell）。"""
    if size >= 256:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0)
    pixels = image.load()
    body = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            red, green, blue, alpha = pixels[x, y]
            body += bytes((blue, green, red, alpha))
    mask_row = ((size + 31) // 32) * 4
    body += bytes(mask_row * size)
    return header + bytes(body)


def _ico(sizes: list[int], *, tile: bool, stroke: str, node: str | None, target: Path) -> None:
    entries: list[tuple[int, bytes]] = []
    for size in sizes:
        entries.append((size, _icon_entry(_paint(size, tile=tile, stroke=stroke, node=node), size)))

    offset = 6 + 16 * len(entries)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    payload = bytearray()
    for size, data in entries:
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        payload += data
        offset += len(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(directory + payload))


def main() -> None:
    PUBLIC_BRAND.mkdir(parents=True, exist_ok=True)

    (PUBLIC_BRAND / "scoutmind-mark.svg").write_text(_svg_mark(LIGHT_MARK, CYAN, "ScoutMind 标识"), encoding="utf-8")
    (PUBLIC_BRAND / "scoutmind-mark-dark.svg").write_text(_svg_mark(WHITE, CYAN, "ScoutMind 标识（深色背景）"), encoding="utf-8")
    (PUBLIC_BRAND / "scoutmind-mark-mono.svg").write_text(_svg_mark(MONO, None, "ScoutMind 单色标识"), encoding="utf-8")
    (PUBLIC_BRAND / "scoutmind-app-icon.svg").write_text(_svg_app_icon(), encoding="utf-8")

    for size in (64, 128, 256, 512, 1024):
        _png(_paint(size, tile=False, stroke=LIGHT_MARK, node=CYAN), PUBLIC_BRAND / f"scoutmind-mark-{size}.png")
        _png(_paint(size, tile=True, stroke=WHITE, node=CYAN), PUBLIC_BRAND / f"scoutmind-app-icon-{size}.png")
    _png(_paint(512, tile=False, stroke=WHITE, node=CYAN), PUBLIC_BRAND / "scoutmind-mark-dark-512.png")
    _png(_paint(512, tile=False, stroke=MONO, node=None), PUBLIC_BRAND / "scoutmind-mark-mono-512.png")

    # Favicon：浏览器标签页在 16–32 px 下需要深色底板保证白 S 可读。
    (PUBLIC_ROOT / "favicon.svg").write_text(_svg_app_icon(), encoding="utf-8")
    _png(_paint(32, tile=True, stroke=WHITE, node=CYAN), PUBLIC_ROOT / "favicon.png")
    _ico([16, 32, 48], tile=True, stroke=WHITE, node=CYAN, target=PUBLIC_ROOT / "favicon.ico")

    # Electron：托盘 / 窗口 / 安装包共用同一套图标。
    _png(_paint(512, tile=True, stroke=WHITE, node=CYAN), DESKTOP_BUILD / "icon.png")
    _ico([16, 32, 48, 64, 128, 256], tile=True, stroke=WHITE, node=CYAN, target=DESKTOP_BUILD / "icon.ico")
    _ico([16, 32, 48, 64, 128, 256], tile=True, stroke=WHITE, node=CYAN, target=PUBLIC_BRAND / "scoutmind.ico")

    with Image.open(DESKTOP_BUILD / "icon.ico") as check:
        sizes = sorted(check.info.get("sizes", []))
    print("generated brand assets")
    print("ico sizes:", [f"{w}x{h}" for w, h in sizes])
    print("mark png:", [f"scoutmind-mark-{size}.png" for size in (64, 128, 256, 512, 1024)])
    print("app icon png:", [f"scoutmind-app-icon-{size}.png" for size in (64, 128, 256, 512, 1024)])


if __name__ == "__main__":
    main()
