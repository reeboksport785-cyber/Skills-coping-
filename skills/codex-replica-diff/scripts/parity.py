#!/usr/bin/env python3
# Derived from replica-skill: Copyright (c) 2026 Jake Schincariol, MIT.
# Adapted for Codex with bounded local I/O. MIT; see ../LICENSE.
"""Weighted feature parity. CSV <=4 MiB, 10k rows, 64 columns, 16k/cell.

--visual JSON scores and --fail-under use finite 0..100 units. --json and
--markdown retained. Empty/all skipped/all extras matrices fail closed.
Unknown priority/clone defaults are reported and cannot pass a release threshold.
"""
import argparse
import json

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _safeio import (SafeError, SafeArgumentParser, safe_text, markdown_text, read_bytes, write_new,
                     load_json, parse_json_bytes, csv_rows, string_list, number, integer,
                     diagnostic, bounded_tree, report_data, review_url)

WEIGHT = {'must': 3, 'should': 2, 'could': 1, 'p0': 3, 'p1': 2, 'p2': 1}
CREDIT = {'yes': 1.0, 'done': 1.0, 'partial': 0.5, 'no': 0.0, '': 0.0, 'todo': 0.0}
PRIORITY_NAME = {3: 'must', 2: 'should', 1: 'could'}
MatrixError = SafeError


def load(path):
    rows = []
    for line, raw in csv_rows(path, ('feature', 'priority', 'clone')):
        if raw['feature']:
            raw['line'] = line
            rows.append(raw)
    if not rows:
        raise SafeError('feature matrix contains no usable rows')
    return rows
def score(rows):
    counted = []
    skipped = []
    extras = []
    unknowns = []
    problems = []
    assumed_original = False
    for row in rows:
        if 'original' not in row and not assumed_original:
            problems.append('original=yes assumed because column absent; original behavior is unverified')
            assumed_original = True
        original = row.get('original', 'yes').lower() or 'unknown'
        if original not in ('yes', 'y', 'true', '1', 'no', 'n', 'false', '0', 'unknown'):
            raise SafeError('original must be yes, no or unknown (yes/no synonyms accepted)')
        if original == 'unknown':
            unknowns.append(row)
            continue
        clone = row.get("clone", "").lower()
        prio = row.get("priority", "").lower()
        if original in ("no", "n", "false", "0"):
            extras.append(row)
            continue
        if clone == "skip":
            skipped.append(row)
            continue
        if prio not in WEIGHT:
            problems.append("line %d: priority '%s' is not must/should/could, counted as could"
                            % (row["line"], row.get("priority", "")))
        if clone not in CREDIT:
            problems.append("line %d: clone '%s' is not yes/partial/no/skip, counted as no"
                            % (row["line"], row.get("clone", "")))
        w = WEIGHT.get(prio, 1)
        c = CREDIT.get(clone, 0.0)
        counted.append(dict(row, weight=w, credit=c))

    if not counted:
        raise SafeError("no original features were evaluated; no release baseline")
    total = sum(r["weight"] for r in counted)
    got = sum(r["weight"] * r["credit"] for r in counted)
    feature_score = 100.0 * got / total if total else 0.0

    areas = {}
    for r in counted:
        a = r.get("area") or "(no area)"
        t = areas.setdefault(a, [0.0, 0.0, 0])
        t[0] += r["weight"] * r["credit"]
        t[1] += r["weight"]
        t[2] += 1
    by_area = sorted(
        ({"area": a, "score": round(100.0 * g / t, 1) if t else 0.0, "features": n}
         for a, (g, t, n) in areas.items()),
        key=lambda d: d["score"])

    missing = [r for r in counted if r["credit"] < 1.0]
    missing.sort(key=lambda r: (-r["weight"], r["credit"], r.get("area", ""), r["feature"]))

    def brief(r):
        return {"feature": r["feature"], "area": r.get("area", ""),
                "priority": PRIORITY_NAME.get(r.get("weight", WEIGHT.get(
                    r.get("priority", "").lower(), 1)), "could"),
                "clone": r.get("clone", "") or "no", "notes": r.get("notes", "")}

    musts = [r for r in counted if r["weight"] == 3]
    return {
        "feature_score": round(feature_score, 1),
        "counted": len(counted),
        "must_have_done": sum(1 for r in musts if r["credit"] == 1.0),
        "must_have_total": len(musts),
        "by_area": by_area,
        "missing": [brief(r) for r in missing],
        "skipped": [brief(r) for r in skipped],
        "extras": [brief(r) for r in extras],
        "unknowns": [dict(brief(r), original="unknown") for r in unknowns],
        "assumed_original": assumed_original,
        "problems": problems,
    }

def visual_scores(paths):
    if len(paths) > 256:
        raise SafeError('at most 256 visual reports are allowed')
    scores = []
    for path in paths:
        data = load_json(path)
        if not isinstance(data, dict) or 'score' not in data:
            raise SafeError('visual report must be an object with a numeric score')
        value = number(data['score'], 'visual score')
        mode = data.get('mode', 'layout')
        if mode not in ('layout', 'pixel'):
            raise SafeError('visual report mode must be layout or pixel')
        if data.get('baseline_evaluated') is False:
            raise SafeError('visual report has no evaluated baseline')
        files = data.get('files', {})
        if not isinstance(files, dict):
            raise SafeError('visual report files must be an object')
        name = files.get('clone', os.fspath(path))
        if not isinstance(name, str):
            raise SafeError('visual report file name must be a string')
        scores.append({'file': safe_text(name, 4096), 'score': value, 'mode': mode})
    return scores
def combine(result, visuals):
    if visuals:
        layout = sum(v["score"] for v in visuals) / len(visuals)
        result["visual"] = visuals
        result["layout_score"] = round(layout, 1)
        result["overall"] = round(0.8 * result["feature_score"] + 0.2 * layout, 1)
    else:
        result["overall"] = result["feature_score"]
    return result
def render(result, markdown=False):
    def display(value):
        if isinstance(value, dict):
            return {k: display(v) for k, v in value.items()}
        if isinstance(value, list):
            return [display(v) for v in value]
        if isinstance(value, str):
            return markdown_text(value, 16384) if markdown else safe_text(value, 16384)
        return value
    result = display(result)
    out = []
    h = "## " if markdown else ""
    out.append("%sParity: %.1f / 100" % (h, result["overall"]))
    out.append("")
    out.append("features %.1f  (%d counted, must-haves %d of %d done)" % (
        result["feature_score"], result["counted"], result["must_have_done"],
        result["must_have_total"]))
    if "layout_score" in result:
        out.append("layout   %.1f  (%d screens compared)" % (
            result["layout_score"], len(result["visual"])))
    if result["must_have_done"] < result["must_have_total"]:
        out.append("")
        out.append("Not shippable yet: %d must-have features are not done."
                   % (result["must_have_total"] - result["must_have_done"]))
    out.append("")
    out.append("%sBy area, weakest first" % h)
    for a in result["by_area"]:
        out.append("- %-28s %5.1f  (%d features)" % (a["area"], a["score"], a["features"]))
    out.append("")
    out.append("%sMissing, in build order" % h)
    if not result["missing"]:
        out.append("- nothing. Every counted feature is done.")
    for m in result["missing"]:
        note = ("  (%s)" % m["notes"]) if m["notes"] else ""
        out.append("- [%s] %s: %s, %s%s" % (m["priority"], m["area"] or "-",
                                             m["feature"], m["clone"], note))
    if result["skipped"]:
        out.append("")
        out.append("%sLeft out on purpose (not scored)" % h)
        for m in result["skipped"]:
            out.append("- %s: %s" % (m["feature"], m["notes"] or "no reason given, add one"))
    if result.get('unknowns'):
        out.append('')
        out.append('%sUnverified original features (not scored; release gate blocked)' % h)
        for row in result['unknowns']:
            out.append('- %s: %s' % (row['feature'], row['notes'] or 'original behavior not verified'))
    if result["extras"]:
        out.append("")
        out.append("%sYours, not in the original (not scored)" % h)
        for m in result["extras"]:
            out.append("- %s" % m["feature"])
    if result.get("visual"):
        out.append("")
        out.append("%sScreens" % h)
        for v in sorted(result["visual"], key=lambda d: d["score"]):
            out.append("- %-40s %5.1f" % (v["file"], v["score"]))
    if result["problems"]:
        out.append("")
        out.append("%sFix in the matrix" % h)
        for p in result["problems"]:
            out.append("- %s" % p)
    return "\n".join(out)

def main(argv=None):
    ap = SafeArgumentParser(description=__doc__)
    ap.add_argument('matrix')
    ap.add_argument('--visual', nargs='*', default=[])
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--markdown', action='store_true')
    ap.add_argument('--fail-under', type=float)
    args = ap.parse_args(argv)
    try:
        if args.fail_under is not None:
            number(args.fail_under, 'fail-under')
        result = combine(score(load(args.matrix)), visual_scores(args.visual))
        print(json.dumps(result, indent=2, allow_nan=False) if args.json else
              render(result, markdown=args.markdown))
        if args.fail_under is not None and (result['problems'] or result.get('unknowns') or
                result['must_have_done'] < result['must_have_total'] or
                result['overall'] < args.fail_under):
            return 1
        return 0
    except (SafeError, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        return diagnostic('parity', exc)


if __name__ == '__main__':
    sys.exit(main())
