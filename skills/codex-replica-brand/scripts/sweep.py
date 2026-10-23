#!/usr/bin/env python3
# Derived from replica-skill: Copyright (c) 2026 Jake Schincariol, MIT.
# Adapted for Codex with bounded local I/O. MIT; see ../LICENSE.
"""Bounded rebrand scan. Stdlib only; no source snippets are emitted.

CLI remains: sweep.py ROOT --avoid NAME --domains HOST --colors HEX --config JSON
--include-replica --json. Limits: 2 MB/file, 128 MiB total, 20k entries, 10k hits.
Symlinks, special/hard-linked inputs, nonexistent roots and zero evaluated files
fail closed. Credential files, dependencies, binary/oversized files are excluded.
"""
import json
import re
import stat
import argparse

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _safeio import (SafeError, SafeArgumentParser, safe_text, markdown_text, read_bytes, write_new,
                     load_json, parse_json_bytes, csv_rows, string_list, number, integer,
                     diagnostic, bounded_tree, report_data, review_url)

from _safeio import open_directory, read_at
SKIP_DIRS = {".git", "node_modules", ".next", ".nuxt", ".svelte-kit", "dist", "build",
             "out", ".vercel", ".turbo", ".cache", "coverage", "__pycache__", ".venv",
             "venv", "Pods", ".expo", "DerivedData", ".gradle"}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
              "Podfile.lock", "Cargo.lock", "poetry.lock"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns", ".pdf", ".zip",
              ".gz", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".mov", ".mp3",
              ".wav", ".avif", ".heic", ".psd", ".sketch", ".fig", ".jar", ".so", ".dylib"}
HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])")
BINARY_ASSET_HINT = re.compile(r"\.(png|jpe?g|svg|webp|gif|ico|woff2?|ttf|otf)$", re.I)
def norm_hex(h):
    h = h.lower().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def build_patterns(avoid, domains):
    pats = []
    for name in avoid:
        name = name.strip()
        if not name:
            continue
        # "Acuity Scheduling" also matches AcuityScheduling and acuity-scheduling
        parts = [re.escape(p) for p in re.split(r"[\s_-]+", name) if p]
        pats.append(("name", name, re.compile(r"[\s_-]?".join(parts), re.I)))
    for d in domains:
        d = d.strip().lower()
        if d:
            pats.append(("domain", d, re.compile(re.escape(d), re.I)))
    return pats

CREDENTIAL_DIRS = {'.ssh', '.aws', '.gnupg', '.kube', '.azure', '.config', 'secrets', 'credentials'}
CREDENTIAL_FILES = {'credentials', 'credentials.json', 'secrets.json', 'secrets.yaml',
                    'secrets.yml', 'id_rsa', 'id_ed25519', '.netrc', '.npmrc', '.pypirc',
                    'service-account.json', 'service_account.json', 'keychain.json'}


def sensitive(name):
    lower = name.lower()
    return (lower == '.env' or lower.startswith('.env.') or lower.endswith('.env') or
            lower in CREDENTIAL_FILES or lower.endswith(('.key', '.pem', '.p12', '.pfx', '.keystore')) or
            'credential' in lower or 'private_key' in lower or 'private-key' in lower)


class SweepHits(list):
    def __init__(self):
        super().__init__()
        self.checked = 0
        self.excluded = 0


def is_binary(path):
    data = read_bytes(path, 2_000_000)
    return os.path.splitext(os.fspath(path))[1].lower() in BINARY_EXT or b'\0' in data[:4096]


def sweep(root, avoid=(), domains=(), colors=(), include_replica=False, max_size=2_000_000):
    integer(max_size, 'max_size', 1, 2_000_000)
    avoid = string_list(avoid, 'avoid', count=128)
    domains = string_list(domains, 'domains', count=128)
    colors = string_list(colors, 'colors', count=128)
    if not (avoid or domains or colors):
        raise SafeError('nothing to search for; supply names, domains or colors')
    pats = build_patterns(avoid, domains)
    if any(rx.pattern == '' for _, _, rx in pats):
        raise SafeError('search name must contain a letter, number or punctuation other than separators')
    if any(not HEX.fullmatch(c) for c in colors):
        raise SafeError('colors must be three- or six-digit hex values prefixed by #')
    cols = {norm_hex(c) for c in colors}
    hits = SweepHits()
    root = os.path.abspath(os.fspath(root))
    root_fd = open_directory(root)
    entries = total = 0

    def add(rel, line, kind, label):
        if len(hits) >= 10_000:
            raise SafeError('scan exceeds 10000-hit limit; narrow the scope')
        hits.append({'file': safe_text(rel, 4096), 'line': line, 'kind': kind,
                     'match': safe_text(label, 256)})

    def walk_error(_):
        raise SafeError('scan cannot read a directory; result is incomplete')

    try:
        for directory, dirs, files, dir_fd in os.fwalk('.', topdown=True, follow_symlinks=False,
                                                       dir_fd=root_fd, onerror=walk_error):
            rel_dir = os.path.normpath(directory)
            if len(rel_dir.split(os.sep)) > 64:
                raise SafeError('scan exceeds 64-directory depth limit')
            entries += len(dirs) + len(files)
            if entries > 20_000:
                raise SafeError('scan exceeds 20000-entry limit; narrow the scope')
            keep = []
            for name in sorted(dirs):
                if (name in SKIP_DIRS or name.lower() in CREDENTIAL_DIRS or sensitive(name) or
                        (name == 'replica' and rel_dir == '.' and not include_replica)):
                    hits.excluded += 1
                    continue
                info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode):
                    raise SafeError('scan refuses symlink or special directories')
                keep.append(name)
                for kind, label, rx in pats:
                    if kind == 'name' and rx.search(name):
                        add(os.path.normpath(os.path.join(rel_dir, name)) + '/', 0, 'path', label)
            dirs[:] = keep
            for name in sorted(files):
                if name in SKIP_FILES or sensitive(name):
                    hits.excluded += 1
                    continue
                rel = os.path.normpath(os.path.join(rel_dir, name))
                info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise SafeError('scan refuses symlink, special or hard-linked files')
                for kind, label, rx in pats:
                    if kind == 'name' and rx.search(name):
                        add(rel, 0, 'path', label)
                if info.st_size > max_size or os.path.splitext(name)[1].lower() in BINARY_EXT:
                    hits.excluded += 1
                    continue
                raw = read_at(dir_fd, name, max_size)
                total += len(raw)
                if total > 128 * 1024 * 1024:
                    raise SafeError('scan exceeds 128 MiB content budget; narrow the scope')
                if not raw or b'\0' in raw[:4096]:
                    hits.excluded += 1
                    continue
                hits.checked += 1
                for i, line in enumerate(raw.decode('utf-8', errors='replace').splitlines(), 1):
                    for kind, label, rx in pats:
                        if rx.search(line):
                            add(rel, i, kind, label)
                    for m in HEX.finditer(line) if cols else ():
                        if norm_hex(m[0]) in cols:
                            add(rel, i, 'color', norm_hex(m[0]))
    finally:
        os.close(root_fd)
    if not hits.checked:
        raise SafeError('no supported text files were evaluated; no clean baseline')
    return hits


def render(hits):
    if not hits:
        return 'Clean within evaluated supported text files. Excluded files are not certified.'
    out = ['%-7s %-18s %s%s' % (h['kind'], safe_text(h['match'], 256), safe_text(h['file'], 4096),
            (':' + str(h['line'])) if h['line'] else '') for h in hits]
    out.append('%d hits. No matched source contents are included.' % len(hits))
    return '\n'.join(out)


def main(argv=None):
    ap = SafeArgumentParser(description=__doc__)
    ap.add_argument('root', nargs='?', default='.')
    for key in ('avoid', 'domains', 'colors'):
        ap.add_argument('--' + key, default='')
    ap.add_argument('--config')
    ap.add_argument('--include-replica', action='store_true')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    try:
        values = {key: [x.strip() for x in getattr(args, key).split(',') if x.strip()]
                  for key in ('avoid', 'domains', 'colors')}
        if args.config:
            cfg = load_json(args.config)
            if not isinstance(cfg, dict) or set(cfg) - set(values):
                raise SafeError('brand JSON accepts only avoid, domains and colors')
            for key in values:
                values[key] += string_list(cfg.get(key, []), key, count=128)
        hits = sweep(args.root, include_replica=args.include_replica, **values)
        print(json.dumps(hits, indent=2, allow_nan=False) if args.json else render(hits))
        print('sweep: %d text files evaluated; %d excluded files/directories' %
              (hits.checked, hits.excluded), file=sys.stderr)
        return 1 if hits else 0
    except (SafeError, OSError, ValueError, TypeError, RecursionError) as exc:
        return diagnostic('sweep', exc)


if __name__ == '__main__':
    sys.exit(main())
