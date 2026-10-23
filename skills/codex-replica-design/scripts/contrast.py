#!/usr/bin/env python3
# Derived from replica-skill: Copyright (c) 2026 Jake Schincariol, MIT.
# Adapted for Codex with bounded local I/O. MIT; see ../LICENSE.
"""WCAG contrast check: tokens.json or two hex colors; --json.

JSON <=1 MiB, depth <=24, <=1024 colors and <=4096 evaluated pairs.
Malformed/empty pairs or unknown size labels fail closed (exit 2).
"""
import argparse
import json
import re

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _safeio import (SafeError, SafeArgumentParser, safe_text, markdown_text, read_bytes, write_new,
                     load_json, parse_json_bytes, csv_rows, string_list, number, integer,
                     diagnostic, bounded_tree, report_data, review_url)

HEX = re.compile(r'^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')
NEEDS = {'normal': (4.5, 7.0), 'large': (3.0, 4.5), 'ui': (3.0, 3.0)}
def parse_hex(value):
    m = HEX.match(value.strip())
    if not m:
        raise ValueError("not a hex colour: %r" % value)
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb):
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg):
    la, lb = luminance(parse_hex(fg)), luminance(parse_hex(bg))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def flatten(obj, prefix=""):
    """{"color": {"text": {"muted": "#..."}}} -> {"text-muted": "#..."}."""
    out = {}
    if isinstance(obj, dict):
        if "value" in obj and isinstance(obj["value"], str):
            out[prefix] = obj["value"]
            return out
        if "$value" in obj and isinstance(obj["$value"], str):
            out[prefix] = obj["$value"]
            return out
        for k, v in obj.items():
            if k.startswith("$") or k.startswith("_"):
                continue
            key = "%s-%s" % (prefix, k) if prefix else k
            out.update(flatten(v, key))
    elif isinstance(obj, str) and HEX.match(obj.strip()):
        out[prefix] = obj.strip()
    return out

def colours(tokens):
    bounded_tree(tokens)
    if not isinstance(tokens, dict):
        raise SafeError('tokens must be a JSON object')
    src = tokens.get('color', tokens.get('colors', tokens.get('colour', {})))
    if not isinstance(src, dict):
        raise SafeError('color/colors/colour must be an object')
    cols = {k: v for k, v in flatten(src).items() if HEX.fullmatch(v)}
    if not cols or len(cols) > 1024:
        raise SafeError('need between 1 and 1024 hex color tokens')
    return cols


def default_pairs(cols):
    fg = [k for k in cols if re.search(r'(^|-)(text|fg|on)(-|$)', k)]
    bg = [k for k in cols if re.search(r'(^|-)(bg|background|surface)(-|$)', k)]
    if len(fg) * len(bg) > 4096:
        raise SafeError('default cross-product exceeds 4096 pairs; specify pairs explicitly')
    return [[f, b] for f in fg for b in bg]


def check(cols, pairs):
    if not isinstance(cols, dict) or not 1 <= len(cols) <= 1024:
        raise SafeError('invalid or empty color map')
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 4096:
        raise SafeError('need between 1 and 4096 pairs')
    rows = []
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) not in (2, 3) or any(
                not isinstance(x, str) or not x or len(x) > 256 for x in pair):
            raise SafeError('each pair must be [foreground, background, optional size]')
        fg, bg = pair[:2]
        size = pair[2] if len(pair) == 3 else 'normal'
        if size not in NEEDS:
            raise SafeError('pair size must be normal, large or ui')
        if fg not in cols or bg not in cols:
            rows.append({'fg': safe_text(fg), 'bg': safe_text(bg), 'size': size, 'error': 'unknown token'})
            continue
        r = ratio(cols[fg], cols[bg])
        aa, aaa = NEEDS[size]
        rows.append({'fg': safe_text(fg), 'bg': safe_text(bg), 'size': size,
                     'ratio': round(r, 2), 'aa': r >= aa, 'aaa': r >= aaa,
                     'fg_hex': cols[fg], 'bg_hex': cols[bg]})
    return rows
def render(rows):
    out = []
    for r in rows:
        if "error" in r:
            out.append("  ??    %-24s on %-20s %s" % (r["fg"], r["bg"], r["error"]))
            continue
        if r["size"] == "ui":
            grade = "PASS" if r["aa"] else "FAIL"
        else:
            grade = "AAA" if r["aaa"] else ("AA" if r["aa"] else "FAIL")
        out.append("  %-5s %5.2f:1  %-24s on %-20s %s" % (
            grade, r["ratio"], r["fg"], r["bg"], "" if r["size"] == "normal" else r["size"]))
    fails = sum(1 for r in rows if "error" in r or not r["aa"])
    out.append("")
    out.append("  %d pairs, %d failing AA" % (len(rows), fails))
    return "\n".join(out)

def main(argv=None):
    ap = SafeArgumentParser(description=__doc__)
    ap.add_argument('args', nargs='+')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    try:
        if len(a.args) == 2 and all(HEX.fullmatch(x) for x in a.args):
            cols, pairs = {'fg': a.args[0], 'bg': a.args[1]}, [['fg', 'bg']]
        elif len(a.args) == 1:
            tokens = load_json(a.args[0])
            cols = colours(tokens)
            pairs = tokens['pairs'] if 'pairs' in tokens else default_pairs(cols)
        else:
            raise SafeError('supply one tokens file or two hex colors')
        rows = check(cols, pairs)
        print(json.dumps(rows, indent=2, allow_nan=False) if a.json else render(rows))
        return 1 if any('error' in r or not r['aa'] for r in rows) else 0
    except (SafeError, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        return diagnostic('contrast', exc)


if __name__ == '__main__':
    sys.exit(main())
