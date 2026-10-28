"""Generate ``desktop/acq.ico`` without any image library.

A Windows icon is a small container of bitmap images. This script draws a flat
teal tile with a white house on it at 256x256, downscales it with a box filter and
writes uncompressed 32-bit bitmaps, which every Windows version and Inno Setup
read correctly (PNG-compressed icon entries are newer and less portable).

Run it only when the design changes; the generated ``desktop/acq.ico`` is committed.
"""

from __future__ import annotations

import struct
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)
MASTER = 256

TEAL = (20, 45, 42)
TEAL_LIGHT = (32, 74, 68)
WHITE = (245, 250, 248)
ACCENT = (126, 217, 87)


def _rounded_alpha(x: float, y: float, size: int, radius: float) -> bool:
    """True inside a rounded square, used for the tile silhouette."""
    inset = size * 0.045
    left, top, right, bottom = inset, inset, size - inset, size - inset
    if not (left <= x <= right and top <= y <= bottom):
        return False
    # Straight bands are always inside; anything else is judged by its nearest corner.
    if left + radius <= x <= right - radius or top + radius <= y <= bottom - radius:
        return True
    centre_x = left + radius if x < left + radius else right - radius
    centre_y = top + radius if y < top + radius else bottom - radius
    return (x - centre_x) ** 2 + (y - centre_y) ** 2 <= radius**2


def _inside_triangle(px: float, py: float, a, b, c) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = sign((px, py), a, b)
    d2 = sign((px, py), b, c)
    d3 = sign((px, py), c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _inside_rect(px: float, py: float, x0, y0, x1, y1) -> bool:
    return x0 <= px <= x1 and y0 <= py <= y1


def master_pixels() -> list[list[tuple[int, int, int, int]]]:
    """256x256 RGBA, top-down. The house is drawn as plain geometry, no fonts."""
    size = MASTER
    radius = size * 0.20
    roof_apex = (size * 0.5, size * 0.20)
    roof_left = (size * 0.15, size * 0.50)
    roof_right = (size * 0.85, size * 0.50)
    body = (size * 0.235, size * 0.47, size * 0.765, size * 0.80)
    door = (size * 0.435, size * 0.60, size * 0.565, size * 0.80)
    window = (size * 0.62, size * 0.585, size * 0.705, size * 0.675)

    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            if not _rounded_alpha(x + 0.5, y + 0.5, size, radius):
                row.append((0, 0, 0, 0))
                continue
            # A gentle vertical gradient keeps the tile from looking flat.
            t = y / (size - 1)
            color = tuple(round(TEAL_LIGHT[i] + (TEAL[i] - TEAL_LIGHT[i]) * t) for i in range(3))
            px, py = x + 0.5, y + 0.5
            if _inside_triangle(px, py, roof_apex, roof_left, roof_right):
                color = WHITE
            elif _inside_rect(px, py, *body):
                color = WHITE
            if _inside_rect(px, py, *door) or _inside_rect(px, py, *window):
                color = ACCENT
            row.append((*color, 255))
        rows.append(row)
    return rows


def downscale(rows, size: int):
    """Box filter: average the master pixels that fall inside each target pixel."""
    step = MASTER / size
    out = []
    for y in range(size):
        line = []
        y0, y1 = int(y * step), max(int(y * step) + 1, int((y + 1) * step))
        for x in range(size):
            x0, x1 = int(x * step), max(int(x * step) + 1, int((x + 1) * step))
            r = g = b = a = n = 0
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    pr, pg, pb, pa = rows[yy][xx]
                    r += pr * pa
                    g += pg * pa
                    b += pb * pa
                    a += pa
                    n += 1
            if a:
                line.append((r // a, g // a, b // a, a // n))
            else:
                line.append((0, 0, 0, 0))
        out.append(line)
    return out


def bmp_entry(pixels, size: int) -> bytes:
    """A 32-bit BGRA bitmap with the AND mask Windows still expects."""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    body = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            r, g, b, a = pixels[y][x]
            body += bytes((b, g, r, a))
    mask_row = (size + 31) // 32 * 4
    mask = bytearray()
    for y in range(size - 1, -1, -1):
        bits = bytearray(mask_row)
        for x in range(size):
            if pixels[y][x][3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bits
    return header + bytes(body) + bytes(mask)


def build(destination: Path) -> Path:
    rows = master_pixels()
    images = [bmp_entry(downscale(rows, size), size) for size in SIZES]
    offset = 6 + 16 * len(SIZES)
    directory = bytearray()
    for size, data in zip(SIZES, images):
        directory += struct.pack("<BBBBHHII", size if size < 256 else 0, size if size < 256 else 0, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"\x00\x00\x01\x00" + struct.pack("<H", len(SIZES)) + bytes(directory) + b"".join(images))
    return destination


if __name__ == "__main__":
    out = build(Path(__file__).resolve().parents[1] / "desktop" / "acq.ico")
    print(f"Wrote {out} ({out.stat().st_size:,} bytes, sizes {', '.join(map(str, SIZES))})")
