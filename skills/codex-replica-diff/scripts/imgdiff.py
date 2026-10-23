#!/usr/bin/env python3
# Derived from replica-skill: Copyright (c) 2026 Jake Schincariol, MIT.
# Adapted for Codex with bounded local I/O. MIT; see ../LICENSE.
"""PNG screenshot diff; stdlib only. --mode layout|pixel, --json, --out,
--width (default 480, 1..4096), --cols (default 12, 1..256), --tolerance (default 24,
0..255), --fail-under (finite 0..100) retained. Limits: 16 MiB encoded PNG,
4 million pixels, 16384 per dimension, 64 MiB inflate, 10000 chunks, 1M grid
cells. Interlace, APNG, invalid CRC/chunk/scanline data are refused. Output is
new 0600 only. No evaluated layout edges means no baseline (CLI exit 2).
"""
import argparse
import json
import math
import struct
import zlib

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _safeio import (SafeError, SafeArgumentParser, safe_text, markdown_text, read_bytes, write_new,
                     load_json, parse_json_bytes, csv_rows, string_list, number, integer,
                     diagnostic, bounded_tree, report_data, review_url)

SIG = b'\x89PNG\r\n\x1a\n'
MAX_PNG = 16 * 1024 * 1024
MAX_PIXELS = 4_000_000
MAX_INFLATE = 64 * 1024 * 1024
MAX_DIMENSION = 16384


class PngError(SafeError):
    pass
def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw, height, stride, bpp):
    rows = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        if pos + 1 + stride > len(raw):
            raise PngError("image data is truncated")
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        elif ftype != 0:
            raise PngError("unknown filter type %d" % ftype)
        rows.append(line)
        prev = line
    return rows


def _samples(line, width, channels, depth):
    """Unpack one unfiltered scanline into a flat list of 8 bit samples."""
    n = width * channels
    if depth == 8:
        return list(line[:n])
    if depth == 16:
        return [line[2 * i] for i in range(n)]
    out = []
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    for byte in line:
        for k in range(per_byte):
            shift = 8 - depth * (k + 1)
            out.append((byte >> shift) & mask)
            if len(out) == n:
                return out
    return out


def _over_white(r, g, b, a):
    if a == 255:
        return (r, g, b)
    inv = 255 - a
    return ((r * a + 255 * inv) // 255, (g * a + 255 * inv) // 255,
            (b * a + 255 * inv) // 255)

def _dimensions(width, height):
    integer(width, 'PNG width', 1, MAX_DIMENSION)
    integer(height, 'PNG height', 1, MAX_DIMENSION)
    if width * height > MAX_PIXELS:
        raise PngError('PNG exceeds 4000000-pixel limit; downscale locally first')


def read_png(path):
    data = read_bytes(path, MAX_PNG)
    if data[:8] != SIG:
        raise PngError('input is not a PNG')
    pos, chunks = 8, 0
    ihdr = palette = transparency = None
    compressed = []
    seen_idat = ended_idat = ended = False
    while pos < len(data):
        chunks += 1
        if chunks > 10000 or pos + 12 > len(data):
            raise PngError('PNG has too many or truncated chunks')
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        if length > len(data) - pos - 12 or not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind):
            raise PngError('invalid PNG chunk length or type')
        body = data[pos + 8:pos + 8 + length]
        checksum = struct.unpack('>I', data[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(kind + body) & 0xffffffff != checksum:
            raise PngError('PNG chunk CRC mismatch')
        pos += length + 12
        if chunks == 1 and kind != b'IHDR':
            raise PngError('PNG must start with IHDR')
        if kind == b'IHDR':
            if ihdr is not None or length != 13 or chunks != 1:
                raise PngError('invalid or duplicate PNG IHDR')
            ihdr = struct.unpack('>IIBBBBB', body)
            width, height, depth, color, compression, filtering, interlace = ihdr
            _dimensions(width, height)
            legal = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                     4: (8, 16), 6: (8, 16)}
            if color not in legal or depth not in legal[color] or compression or filtering:
                raise PngError('unsupported PNG color/depth/compression/filter combination')
            if interlace:
                raise PngError('interlaced PNG is refused; re-save without interlacing')
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            stride = (width * channels * depth + 7) // 8
            expected = (stride + 1) * height
            if expected > MAX_INFLATE:
                raise PngError('PNG exceeds 64 MiB inflated-byte limit')
        elif kind == b'PLTE':
            if seen_idat or palette is not None or not 3 <= length <= 768 or length % 3 or color in (0, 4):
                raise PngError('invalid PNG palette')
            palette = [tuple(body[i:i + 3]) for i in range(0, length, 3)]
            if color == 3 and len(palette) > (1 << depth):
                raise PngError('PNG palette has too many entries for bit depth')
        elif kind == b'tRNS':
            if seen_idat or transparency is not None or color in (4, 6):
                raise PngError('invalid PNG transparency chunk')
            if ((color == 0 and length != 2) or (color == 2 and length != 6) or
                    (color == 3 and (palette is None or not 1 <= length <= len(palette)))):
                raise PngError('invalid PNG transparency length or ordering')
            transparency = body
        elif kind == b'IDAT':
            if ended_idat or (color == 3 and palette is None):
                raise PngError('invalid PNG image-data ordering')
            seen_idat = True
            compressed.append(body)
        elif kind == b'IEND':
            if length or not seen_idat or pos != len(data):
                raise PngError('invalid PNG end or trailing data')
            ended = True
            break
        else:
            if kind in (b'acTL', b'fcTL', b'fdAT'):
                raise PngError('animated PNG is unsupported; supply a static screenshot')
            if 65 <= kind[0] <= 90:
                raise PngError('unknown critical PNG chunk')
            if seen_idat:
                ended_idat = True
    if ihdr is None or not ended:
        raise PngError('PNG is missing IHDR, image data or IEND')
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(b''.join(compressed), expected + 1)
    except zlib.error:
        raise PngError('invalid compressed PNG data') from None
    if (len(raw) != expected or not inflater.eof or inflater.unconsumed_tail or inflater.unused_data):
        raise PngError('PNG inflated length does not match bounded dimensions')
    lines = _unfilter(raw, height, stride, max(1, channels * depth // 8))
    rows = []
    transparent = None
    if transparency is not None and color in (0, 2):
        transparent = tuple(struct.unpack('>' + 'H' * (len(transparency) // 2), transparency))
        if any(x >= (1 << depth) for x in transparent):
            raise PngError('transparency sample exceeds PNG bit depth')
    for line in lines:
        if depth == 16:
            native = [(line[i] << 8) | line[i + 1] for i in range(0, len(line), 2)]
            samples = [x >> 8 for x in native]
        else:
            native = _samples(line, width, channels, depth)
            samples = [x * (255 // ((1 << depth) - 1)) for x in native] if depth < 8 and color == 0 else native
        row = []
        for x in range(width):
            i = x * channels
            if color == 0:
                gray = samples[i]
                alpha = 0 if transparent == (native[i],) else 255
                pixel = _over_white(gray, gray, gray, alpha)
            elif color == 2:
                alpha = 0 if transparent == tuple(native[i:i + 3]) else 255
                pixel = _over_white(*samples[i:i + 3], alpha)
            elif color == 3:
                index = native[i]
                if index >= len(palette):
                    raise PngError('PNG sample references a missing palette entry')
                alpha = transparency[index] if transparency is not None and index < len(transparency) else 255
                pixel = _over_white(*palette[index], alpha)
            elif color == 4:
                pixel = _over_white(samples[i], samples[i], samples[i], samples[i + 1])
            else:
                pixel = _over_white(*samples[i:i + 4])
            row.append(pixel)
        rows.append(row)
    return width, height, rows


def _image_shape(image):
    if not isinstance(image, (tuple, list)) or len(image) != 3:
        raise PngError('invalid decoded image')
    width, height, rows = image
    _dimensions(width, height)
    if not isinstance(rows, list) or len(rows) != height or any(
            not isinstance(row, list) or len(row) != width for row in rows):
        raise PngError('decoded image rows do not match dimensions')


def write_png(path, width, height, rows):
    _image_shape((width, height, rows))
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for pixel in row:
            if not isinstance(pixel, (list, tuple)) or len(pixel) != 3 or any(
                    isinstance(c, bool) or not isinstance(c, int) or not 0 <= c <= 255 for c in pixel):
                raise PngError('output pixels must be 8-bit RGB triples')
            raw.extend(pixel)

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    encoded = SIG + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b'')
    write_new(path, encoded, MAX_PNG)
def resize(rows, width, height, new_w, new_h):
    """Nearest-neighbour resize. Good enough for structure, and fast."""
    xs = [min(width - 1, int(x * width / new_w)) for x in range(new_w)]
    ys = [min(height - 1, int(y * height / new_h)) for y in range(new_h)]
    return [[rows[y][x] for x in xs] for y in ys]


def to_width(img, target):
    w, h, rows = img
    if w == target:
        return w, h, rows
    new_h = max(1, int(round(h * target / float(w))))
    return target, new_h, resize(rows, w, h, target, new_h)


def gray(rows):
    return [[(299 * r + 587 * g + 114 * b) // 1000 for r, g, b in row] for row in rows]


def edges(g, threshold):
    h = len(g)
    w = len(g[0]) if h else 0
    out = []
    for y in range(h):
        row = g[y]
        below = g[y + 1] if y + 1 < h else row
        e = []
        for x in range(w):
            right = row[x + 1] if x + 1 < w else row[x]
            e.append(1 if abs(right - row[x]) + abs(below[x] - row[x]) > threshold else 0)
        out.append(e)
    return out


def _regions(flags, n_rows, n_cols):
    """Group flagged grid cells into rectangles (4-connected)."""
    seen = set()
    regions = []
    for r in range(n_rows):
        for c in range(n_cols):
            if not flags[r][c] or (r, c) in seen:
                continue
            stack = [(r, c)]
            seen.add((r, c))
            cells = []
            while stack:
                cr, cc = stack.pop()
                cells.append((cr, cc))
                for nr, nc in ((cr + 1, cc), (cr - 1, cc), (cr, cc + 1), (cr, cc - 1)):
                    if 0 <= nr < n_rows and 0 <= nc < n_cols and flags[nr][nc] \
                            and (nr, nc) not in seen:
                        seen.add((nr, nc))
                        stack.append((nr, nc))
            rs = [x[0] for x in cells]
            cs = [x[1] for x in cells]
            regions.append((min(rs), min(cs), max(rs), max(cs), len(cells)))
    regions.sort(key=lambda t: -t[4])
    return regions
def compare(img_a, img_b, mode="layout", width=480, cols=12, tolerance=24,
            edge_threshold=40):
    """Compare two decoded images. Returns (report dict, diff rows)."""
    if mode not in ('layout', 'pixel'):
        raise PngError('mode must be layout or pixel')
    integer(width, 'width', 1, 4096)
    integer(cols, 'cols', 1, 256)
    integer(tolerance, 'tolerance', 0, 255)
    integer(edge_threshold, 'edge_threshold', 0, 510)
    _image_shape(img_a)
    _image_shape(img_b)
    wa, ha, _ = img_a
    wb, hb, _ = img_b
    target = min(width, wa, wb)
    a = to_width(img_a, target)
    b = to_width(img_b, target)
    w = target
    h = min(a[1], b[1])
    cell_budget = max(1, w // cols)
    if ((h + cell_budget - 1) // cell_budget) * cols > 1_000_000:
        raise PngError('comparison exceeds 1000000 grid-cell limit; reduce cols')
    ra = a[2][:h]
    rb = b[2][:h]
    height_delta = (b[1] - a[1]) / float(a[1]) * 100.0 if a[1] else 0.0
    to_orig = wa / float(w)

    ga = gray(ra)
    dim = [[(200 + v // 5,) * 3 for v in row] for row in ga]
    report = {
        "mode": mode,
        "original": {"width": wa, "height": ha},
        "clone": {"width": wb, "height": hb},
        "compared_at": {"width": w, "height": h},
        "height_delta_pct": round(height_delta, 1),
    }

    if mode == "pixel":
        changed = 0
        flags_px = []
        for y in range(h):
            fr = []
            for x in range(w):
                pa, pb = ra[y][x], rb[y][x]
                d = max(abs(pa[0] - pb[0]), abs(pa[1] - pb[1]), abs(pa[2] - pb[2]))
                hit = d > tolerance
                fr.append(hit)
                if hit:
                    changed += 1
                    dim[y][x] = (220, 30, 30)
            flags_px.append(fr)
        total = w * h or 1
        score = 100.0 * (1 - changed / float(total))
        report["changed_pixels"] = changed
        report["baseline_evaluated"] = total > 0
        report["evaluated_pixels"] = total
        # Summarise pixel hits as grid regions so the report stays readable.
        cell = max(1, w // cols)
        n_rows = int(math.ceil(h / float(cell)))
        flags = [[False] * cols for _ in range(n_rows)]
        for r in range(n_rows):
            for c in range(cols):
                hits = 0
                area = 0
                for y in range(r * cell, min(h, (r + 1) * cell)):
                    row = flags_px[y]
                    for x in range(c * cell, min(w, (c + 1) * cell)):
                        area += 1
                        hits += row[x]
                flags[r][c] = area > 0 and hits / float(area) > 0.02
    else:
        ea = edges(ga, edge_threshold)
        eb = edges(gray(rb), edge_threshold)
        cell = max(1, w // cols)
        n_rows = int(math.ceil(h / float(cell)))
        flags = [[False] * cols for _ in range(n_rows)]
        sims = []
        for r in range(n_rows):
            for c in range(cols):
                y0, y1 = r * cell, min(h, (r + 1) * cell)
                x0, x1 = c * cell, min(w, (c + 1) * cell)
                area = (y1 - y0) * (x1 - x0)
                if area <= 0:
                    continue
                da = sum(sum(ea[y][x0:x1]) for y in range(y0, y1)) / float(area)
                db = sum(sum(eb[y][x0:x1]) for y in range(y0, y1)) / float(area)
                top = max(da, db)
                if top < 0.01:
                    continue  # empty in both: says nothing about the layout
                sim = 1.0 - abs(da - db) / top
                sims.append(sim)
                if sim < 0.6:
                    flags[r][c] = True
                    for y in range(y0, y1):
                        for x in range(x0, x1):
                            g0 = dim[y][x][0]
                            dim[y][x] = (min(255, g0 + 30), g0 // 3, g0 // 3)
        score = 100.0 * sum(sims) / len(sims) if sims else 0.0
        report["baseline_evaluated"] = bool(sims)
        report["evaluated_cells"] = len(sims)

    regions = []
    for r0, c0, r1, c1, n in _regions(flags, len(flags), cols):
        x = int(c0 * cell * to_orig)
        y = int(r0 * cell * to_orig)
        regions.append({
            "x": x, "y": y,
            "w": min(wa - x, int((c1 - c0 + 1) * cell * to_orig)),
            "h": min(ha - y, int((r1 - r0 + 1) * cell * to_orig)),
            "cells": n,
            "where": _where(r0, c0, r1, c1, len(flags), cols),
        })
    report["score"] = round(score, 1)
    report["verdict"] = verdict(score)
    report["regions"] = regions
    return report, dim
def _where(r0, c0, r1, c1, n_rows, n_cols):
    mid_r = (r0 + r1) / 2.0 / max(1, n_rows - 1) if n_rows > 1 else 0.5
    mid_c = (c0 + c1) / 2.0 / max(1, n_cols - 1) if n_cols > 1 else 0.5
    v = "top" if mid_r < 0.34 else ("bottom" if mid_r > 0.66 else "middle")
    hz = "left" if mid_c < 0.34 else ("right" if mid_c > 0.66 else "centre")
    return "%s %s" % (v, hz)


def verdict(score):
    if score >= 90:
        return "matches"
    if score >= 75:
        return "close"
    if score >= 50:
        return "partly"
    return "different"
def render_text(report, a_name, b_name):
    a_name, b_name = safe_text(a_name, 4096), safe_text(b_name, 4096)
    lines = []
    bar = int(round(report["score"] / 100.0 * 24))
    lines.append("  %s vs %s" % (a_name, b_name))
    lines.append("  %-6s %s%s  %5.1f  %s" % (
        report["mode"].upper(), "#" * bar, "." * (24 - bar), report["score"],
        report["verdict"].upper()))
    hd = report["height_delta_pct"]
    if abs(hd) >= 5:
        lines.append("  height: the clone is %.0f%% %s than the original"
                     % (abs(hd), "taller" if hd > 0 else "shorter"))
    if report["regions"]:
        lines.append("  where they differ (original's pixels, biggest first):")
        for reg in report["regions"][:8]:
            lines.append("    %-14s x=%d y=%d w=%d h=%d" % (
                reg["where"], reg["x"], reg["y"], reg["w"], reg["h"]))
    else:
        lines.append("  no differing regions")
    return "\n".join(lines)

def main(argv=None):
    ap = SafeArgumentParser(description=__doc__)
    ap.add_argument('original')
    ap.add_argument('clone')
    ap.add_argument('--mode', choices=('layout', 'pixel'), default='layout')
    ap.add_argument('--width', type=int, default=480)
    ap.add_argument('--cols', type=int, default=12)
    ap.add_argument('--tolerance', type=int, default=24)
    ap.add_argument('--out')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--fail-under', type=float)
    args = ap.parse_args(argv)
    try:
        integer(args.width, 'width', 1, 4096)
        integer(args.cols, 'cols', 1, 256)
        integer(args.tolerance, 'tolerance', 0, 255)
        if args.fail_under is not None:
            number(args.fail_under, 'fail-under')
        a, b = read_png(args.original), read_png(args.clone)
        report, diff = compare(a, b, mode=args.mode, width=args.width, cols=args.cols,
                               tolerance=args.tolerance)
        report['files'] = {'original': safe_text(args.original, 4096), 'clone': safe_text(args.clone, 4096)}
        if not report['baseline_evaluated']:
            raise PngError('no layout edge cells were evaluated; use meaningful screenshots or pixel mode')
        if args.out:
            write_png(args.out, report['compared_at']['width'], report['compared_at']['height'], diff)
            report['diff_image'] = safe_text(args.out, 4096)
        print(json.dumps(report, indent=2, allow_nan=False) if args.json else
              render_text(report, args.original, args.clone))
        if args.out and not args.json:
            print('  diff image: ' + safe_text(args.out, 4096))
        return 1 if args.fail_under is not None and report['score'] < args.fail_under else 0
    except (SafeError, OSError, ValueError, TypeError, KeyError, IndexError,
            struct.error, zlib.error, RecursionError) as exc:
        return diagnostic('imgdiff', exc)


if __name__ == '__main__':
    sys.exit(main())
