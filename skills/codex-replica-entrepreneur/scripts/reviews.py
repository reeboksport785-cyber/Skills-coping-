#!/usr/bin/env python3
# Derived from replica-skill: Copyright (c) 2026 Jake Schincariol, MIT.
# Adapted for Codex with bounded local I/O. MIT; see ../LICENSE.
"""Rank supplied sourced reviews; no fetching or remote calls.

CSV <=4 MiB, <=10k rows, <=64 columns, <=16k characters/cell. --themes only
accepts audited shipped regex or custom match_mode: literal themes. Arbitrary
custom regex is refused. Custom limits: 64 themes, 256 total patterns, 128 chars/pattern.
Reports redact email/phone patterns; public URL query/fragment are preserved.
Rows with credential/contact URL parameters are dropped. --out creates
a new regular 0600 file and never overwrites. --months 1..1200. --json retained.
"""
import argparse
import datetime as _dt
import hashlib
import json
import re

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _safeio import (SafeError, SafeArgumentParser, safe_text, markdown_text, read_bytes, write_new,
                     load_json, parse_json_bytes, csv_rows, string_list, number, integer,
                     diagnostic, bounded_tree, report_data, review_url)

DEFAULT_THEMES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'assets', 'themes.json')
THEMES_SHA256 = '008d337c9dd3c33adb1aad24bb4c35feed776c5370b6b295cd67f306aaa3d754'
SENTENCE = re.compile(r'(?<=[.!?])\s+|\n+')
FeedbackError = SafeError


def load_themes(path=DEFAULT_THEMES):
    raw = read_bytes(path)
    data = parse_json_bytes(raw)
    if hashlib.sha256(raw).hexdigest() != THEMES_SHA256:
        if not isinstance(data, dict) or data.get('match_mode') != 'literal':
            raise SafeError('custom themes require match_mode: literal; arbitrary regex is refused')
        entries = data.get('themes', [])
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise SafeError('custom themes need between 1 and 64 entries')
        themes = []
        seen = set()
        total = 0
        for entry in entries:
            if not isinstance(entry, dict):
                raise SafeError('custom theme must be an object')
            ident = entry.get('id')
            if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', ident) or ident in seen:
                raise SafeError('custom theme IDs must be unique short identifiers')
            seen.add(ident)
            label, kind = entry.get('label', ident), entry.get('kind', 'complaint')
            if not isinstance(label, str) or not 1 <= len(label) <= 128 or kind not in ('complaint', 'request'):
                raise SafeError('invalid custom theme label or kind')
            patterns = string_list(entry.get('patterns', []), 'literal patterns', count=32, length=128)
            if not patterns:
                raise SafeError('each custom theme needs at least one literal pattern')
            total += len(patterns)
            themes.append({'id': ident, 'label': label, 'kind': kind,
                           'patterns': [re.compile(re.escape(p), re.I) for p in patterns]})
        requests = string_list(data.get('request_patterns', []), 'literal request_patterns', count=64, length=128)
        if total + len(requests) > 256:
            raise SafeError('custom themes exceed 256 total literal patterns')
        return themes, [re.compile(re.escape(p), re.I) for p in requests]
    themes = [{'id': t['id'], 'label': t.get('label', t['id']),
               'kind': t.get('kind', 'complaint'),
               'patterns': [re.compile(p, re.I) for p in t.get('patterns', [])]}
              for t in data.get('themes', [])]
    return themes, [re.compile(p, re.I) for p in data.get('request_patterns', [])]
def parse_date(text):
    text = (text or "").strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y-%m", 7)):
        try:
            return _dt.datetime.strptime(text[:n], fmt).date()
        except ValueError:
            continue
    return None


def parse_rating(text):
    text = (text or "").strip()
    if not text:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    value = float(m.group(1))
    if value < 1 or value > 5:
        return None
    return value

def load_reviews(path):
    kept, dropped, dupes = [], 0, 0
    seen = set()
    for line, row in csv_rows(path, ('url', 'text')):
        text = row.get('text', '')
        try:
            url = review_url(row.get('url', ''))
        except SafeError:
            dropped += 1
            continue
        if not text:
            dropped += 1
            continue
        key = re.sub(r'\W+', ' ', text.lower()).strip()
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        kept.append({'line': line, 'source': row.get('source', '') or _host(url),
                     'url': url, 'date': parse_date(row.get('date', '')),
                     'rating': parse_rating(row.get('rating', '')), 'text': text})
    return kept, dropped, dupes
def _host(url):
    m = re.match(r"^https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else "unknown"


def weight(review, today, months):
    r = review["rating"]
    w = 0.6 if r is None else (6.0 - r) / 5.0
    if review["date"] is not None and today is not None:
        age_days = (today - review["date"]).days
        if age_days > months * 30.4:
            w *= 0.5
    return w


def snippet(text, pattern, limit=220):
    """The first sentence of text that matches pattern, verbatim."""
    for sent in SENTENCE.split(text):
        if pattern.search(sent):
            s = sent.strip()
            if len(s) > limit:
                m = pattern.search(s)
                start = max(0, m.start() - limit // 2)
                s = s[start:start + limit].strip()
                s = ("..." if start > 0 else "") + s + "..."
            return s
    s = text.strip()
    return s if len(s) <= limit else s[:limit].rstrip() + "..."
def _analyse(reviews, themes, request_patterns, today=None, months=18):
    if today is None:
        today = _dt.date.today()
    results = {t["id"]: {"id": t["id"], "label": t["label"], "kind": t["kind"],
                         "reviews": [], "score": 0.0} for t in themes}
    requests = []
    unthemed_negative = []
    for rv in reviews:
        w = weight(rv, today, months)
        matched = False
        for t in themes:
            hit = next((p for p in t["patterns"] if p.search(rv["text"])), None)
            if hit is None:
                continue
            matched = True
            res = results[t["id"]]
            res["score"] += w
            res["reviews"].append({"rv": rv, "quote": snippet(rv["text"], hit)})
        req = next((p for p in request_patterns if p.search(rv["text"])), None)
        if req is not None:
            requests.append({"quote": snippet(rv["text"], req), "url": rv["url"],
                             "source": rv["source"], "rating": rv["rating"]})
        if not matched and rv["rating"] is not None and rv["rating"] <= 2:
            unthemed_negative.append(rv)

    total = len(reviews) or 1
    ranked = []
    for res in results.values():
        items = res["reviews"]
        if not items:
            continue
        rated = [x["rv"]["rating"] for x in items if x["rv"]["rating"] is not None]
        sources = sorted({x["rv"]["source"] for x in items})
        # Lowest rated first, then shortest, so the quotes shown are the sharpest.
        items.sort(key=lambda x: (x["rv"]["rating"] if x["rv"]["rating"] is not None else 3,
                                  len(x["quote"])))
        ranked.append({
            "id": res["id"], "label": res["label"], "kind": res["kind"],
            "score": round(res["score"], 2),
            "count": len(items),
            "share_pct": round(100.0 * len(items) / total, 1),
            "avg_rating": round(sum(rated) / len(rated), 2) if rated else None,
            "sources": sources,
            "thin": len(items) < 3 or len(sources) < 2,
            "quotes": [{"quote": x["quote"], "url": x["rv"]["url"],
                        "source": x["rv"]["source"], "rating": x["rv"]["rating"]}
                       for x in items[:3]],
        })
    ranked.sort(key=lambda d: (-d["score"], -d["count"], d["id"]))
    return {
        "reviews": len(reviews),
        "sources": sorted({r["source"] for r in reviews}),
        "rated": sum(1 for r in reviews if r["rating"] is not None),
        "themes": ranked,
        "requests": requests,
        "unthemed_negative": [{"url": r["url"], "source": r["source"],
                               "rating": r["rating"], "text": r["text"][:220]}
                              for r in unthemed_negative],
    }

def analyse(reviews, themes, request_patterns, today=None, months=18):
    integer(months, 'months', 1, 1200)
    if not reviews or len(reviews) > 10000:
        raise SafeError('need between 1 and 10000 usable reviews')
    return report_data(_analyse(reviews, themes, request_patterns, today=today, months=months))
def _stars(r):
    return "-" if r is None else ("%g*" % r)
def render(result, dropped=0, dupes=0):
    def escaped(value):
        if isinstance(value, dict):
            return {key: escaped(val) for key, val in value.items()}
        if isinstance(value, list):
            return [escaped(val) for val in value]
        return markdown_text(value, 16384) if isinstance(value, str) else value
    result = escaped(report_data(result))
    out = ["# What users of the original hate and want", "", "Contact patterns are redacted; quotes may contain redaction markers. Public provenance URLs are preserved; credential/contact URLs are refused.", ""]
    out.append("%d reviews from %d sources (%s). %d had star ratings." % (
        result["reviews"], len(result["sources"]), ", ".join(result["sources"]) or "none",
        result["rated"]))
    if dropped:
        out.append("%d rows dropped: missing text or missing/unsafe provenance URL. Nothing is counted without "
                   "its source." % dropped)
    if dupes:
        out.append("%d duplicate reviews removed." % dupes)
    if result["reviews"] < 30:
        out.append("")
        out.append("Small sample. Under 30 reviews supports a direction, not a "
                   "ranking. Collect more before you bet the roadmap on it.")
    for kind, title in (("complaint", "What they hate"), ("request", "What they ask for")):
        rows = [t for t in result["themes"] if t["kind"] == kind]
        out.append("")
        out.append("## %s" % title)
        out.append("")
        if not rows:
            out.append("Nothing matched. Read the reviews by hand.")
            continue
        out.append("| rank | theme | score | reviews | share | avg stars | sources |")
        out.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, t in enumerate(rows, 1):
            out.append("| %d | %s%s | %.1f | %d | %.0f%% | %s | %d |" % (
                i, t["label"], " (thin)" if t["thin"] else "", t["score"], t["count"],
                t["share_pct"], "-" if t["avg_rating"] is None else "%.1f" % t["avg_rating"],
                len(t["sources"])))
        for t in rows[:6]:
            out.append("")
            out.append("**%s**" % t["label"])
            for q in t["quotes"]:
                out.append('- "%s" (%s, %s) %s' % (q["quote"], q["source"],
                                                   _stars(q["rating"]), q["url"]))
    if result["requests"]:
        out.append("")
        out.append("## Asked for in their own words")
        out.append("")
        for q in result["requests"][:25]:
            out.append('- "%s" (%s, %s) %s' % (q["quote"], q["source"],
                                               _stars(q["rating"]), q["url"]))
    if result["unthemed_negative"]:
        out.append("")
        out.append("## Read these by hand")
        out.append("")
        out.append("Low ratings that matched no theme. Either noise, or a theme "
                   "themes.json does not have yet. Often the most useful part.")
        out.append("")
        for r in result["unthemed_negative"][:15]:
            out.append('- (%s, %s) %s: "%s"' % (r["source"], _stars(r["rating"]),
                                               r["url"], r["text"]))
    return "\n".join(out) + "\n"

def main(argv=None):
    ap = SafeArgumentParser(description=__doc__)
    ap.add_argument('reviews')
    ap.add_argument('--themes', default=DEFAULT_THEMES)
    ap.add_argument('--months', type=int, default=18)
    ap.add_argument('--today')
    ap.add_argument('--out')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    try:
        integer(args.months, 'months', 1, 1200)
        if args.json and args.out:
            raise SafeError('--json and --out cannot be combined; choose stdout JSON or a Markdown file')
        today = parse_date(args.today) if args.today else None
        if args.today and (today is None or today.isoformat() != args.today):
            raise SafeError('--today must be a valid YYYY-MM-DD date')
        themes, req = load_themes(args.themes)
        reviews, dropped, dupes = load_reviews(args.reviews)
        if not reviews:
            raise SafeError('no usable sourced review rows')
        result = analyse(reviews, themes, req, today=today, months=args.months)
        result.update({'dropped': dropped, 'duplicates': dupes,
                       'privacy': 'email/phone patterns redacted; public source URLs preserved; credential/contact URLs refused'})
        if args.json:
            print(json.dumps(result, indent=2, default=str, allow_nan=False))
        else:
            text = render(result, dropped, dupes)
            if args.out:
                write_new(args.out, text, maximum=16 * 1024 * 1024)
                print('wrote ' + safe_text(args.out, 4096))
            else:
                sys.stdout.write(text)
        return 0
    except (SafeError, OSError, ValueError, TypeError, KeyError, re.error, RecursionError) as exc:
        return diagnostic('reviews', exc)


if __name__ == '__main__':
    sys.exit(main())
