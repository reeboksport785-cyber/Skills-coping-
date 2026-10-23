"""Bounded local I/O for the Codex Replica adaptations; standard library only.

Derived tools: Copyright (c) 2026 Jake Schincariol, MIT; see ../LICENSE.
Adapted for Codex with bounded local I/O; MIT, see ../LICENSE.
"""
import argparse
import csv
import io
import json
import math
import os
import re
import stat
import sys
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit

MAX_JSON = 1_048_576
MAX_CSV = 4_194_304
MAX_ROWS = 10_000
MAX_COLS = 64
MAX_CELL = 16_384
MAX_NODES = 30_000
MAX_DEPTH = 24


class SafeError(ValueError):
    pass


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'invalid command-line arguments; use --help\n')


def safe_text(value, limit=1024):
    """Escape control/format characters; never emit terminal instructions."""
    text = str(value)
    out = []
    for char in text[:limit]:
        if unicodedata.category(char).startswith("C"):
            code = ord(char)
            out.append("\\x%02x" % code if code <= 255 else "\\u%04x" % code)
        else:
            out.append(char)
    if len(text) > limit:
        out.append("...[truncated]")
    return "".join(out)


def markdown_text(value, limit=1024):
    text = safe_text(value, limit)
    return re.sub(r"([\\`*_{}\[\]()<>|!#])", r"\\\1", text)


def _parent(path):
    """Walk every directory through fd-relative O_NOFOLLOW opens (POSIX)."""
    if not all(hasattr(os, x) for x in ("O_NOFOLLOW", "O_DIRECTORY")):
        raise SafeError('POSIX no-follow operations required: use Linux, macOS or WSL')
    path = os.fspath(path)
    if not isinstance(path, str) or not path or "\0" in path or len(path) > 4096:
        raise SafeError("invalid local path")
    absolute = os.path.abspath(path)
    parts = absolute.split("/")[1:]
    if not parts or not parts[-1]:
        raise SafeError("a regular file path is required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                              os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def open_directory(path):
    """Return an owned directory fd. All path components must be real dirs."""
    if not all(hasattr(os, x) for x in ('O_NOFOLLOW', 'O_DIRECTORY', 'fwalk')):
        raise SafeError('POSIX no-follow operations required: use Linux, macOS or WSL')
    absolute = os.path.abspath(os.fspath(path))
    if absolute == "/":
        return os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    parent, name = _parent(absolute)
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                       os.O_CLOEXEC, dir_fd=parent)
    finally:
        os.close(parent)


def read_at(parent, name, maximum=MAX_JSON):
    """Read a basename anchored to an already verified directory descriptor."""
    if not isinstance(name, str) or name in ('', '.', '..') or '/' in name or '\0' in name:
        raise SafeError('input basename must not contain path components')
    fd = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                     os.O_CLOEXEC, dir_fd=parent)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SafeError("input must be a regular file with one hard link")
        if info.st_size > maximum:
            raise SafeError("input exceeds %d-byte limit" % maximum)
        with os.fdopen(fd, "rb") as fh:
            fd = None
            data = fh.read(maximum + 1)
        if len(data) > maximum:
            raise SafeError("input exceeds %d-byte limit" % maximum)
        return data
    except OSError:
        raise SafeError("cannot open regular input; missing, inaccessible or unsafe path") from None
    finally:
        if fd is not None:
            os.close(fd)


def read_bytes(path, maximum=MAX_JSON):
    parent, name = _parent(path)
    try:
        return read_at(parent, name, maximum)
    finally:
        os.close(parent)


def write_new(path, data, maximum=64 * 1024 * 1024):
    """Create a new 0600 regular file; refuse existing files and symlinks."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, bytes) or len(data) > maximum:
        raise SafeError("output exceeds %d-byte limit" % maximum)
    parent, name = _parent(path)
    fd = None
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                     os.O_CLOEXEC, 0o600, dir_fd=parent)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SafeError("output must be a new regular file with one hard link")
        with os.fdopen(fd, "wb") as fh:
            fd = None
            fh.write(data)
    except OSError:
        raise SafeError("cannot create output; it must not exist and parents must be real directories") from None
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def _pairs(items):
    data = {}
    for key, value in items:
        if key in data:
            raise SafeError("duplicate JSON key")
        data[key] = value
    return data


def _constant(value):
    raise SafeError("non-finite JSON numbers are not allowed")


def bounded_tree(value):
    stack = [(value, 0)]
    count = 0
    while stack:
        obj, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise SafeError("JSON tree exceeds node/depth limits")
        if isinstance(obj, dict):
            for key, val in obj.items():
                if not isinstance(key, str) or len(key) > MAX_CELL:
                    raise SafeError("invalid JSON key")
                stack.append((val, depth + 1))
        elif isinstance(obj, list):
            stack.extend((val, depth + 1) for val in obj)
        elif isinstance(obj, str):
            if len(obj) > MAX_CELL:
                raise SafeError("JSON string exceeds %d-character limit" % MAX_CELL)
        elif isinstance(obj, float) and not math.isfinite(obj):
            raise SafeError("non-finite JSON numbers are not allowed")
    return value


def parse_json_bytes(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_JSON:
        raise SafeError('JSON exceeds input byte limit')
    # Bound nesting before the JSON parser can recurse; braces in strings ignored.
    depth = 0
    quoted = escaped = False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > MAX_DEPTH:
                raise SafeError("JSON nesting exceeds %d" % MAX_DEPTH)
        elif byte in (93, 125):
            depth -= 1
    try:
        data = json.loads(raw.decode("utf-8-sig"), parse_constant=_constant,
                          object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise SafeError("invalid or unsupported JSON") from None
    return bounded_tree(data)


def load_json(path):
    return parse_json_bytes(read_bytes(path, MAX_JSON))


def csv_rows(path, required):
    try:
        text = read_bytes(path, MAX_CSV).decode("utf-8-sig")
    except UnicodeError:
        raise SafeError("CSV must be UTF-8") from None
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        raw_header = next(reader, None)
        if raw_header is None or not raw_header or len(raw_header) > MAX_COLS:
            raise SafeError("CSV has no usable header or too many columns")
        header = [x.strip().lower() for x in raw_header]
        if any(not x or len(x) > 128 for x in header) or len(set(header)) != len(header):
            raise SafeError("CSV headers must be unique nonempty names")
        if not set(required) <= set(header):
            raise SafeError("CSV requires columns: " + ", ".join(required))
        out = []
        for cells in reader:
            if not cells:
                continue
            if len(out) >= MAX_ROWS:
                raise SafeError("CSV exceeds %d-row limit" % MAX_ROWS)
            if len(cells) != len(header):
                raise SafeError("CSV row has a different number of cells than the header")
            if any(len(x) > MAX_CELL for x in cells):
                raise SafeError("CSV cell exceeds %d-character limit" % MAX_CELL)
            out.append((reader.line_num, dict(zip(header, (x.strip() for x in cells)))))
        return out
    except csv.Error:
        raise SafeError("malformed CSV or field too large") from None


def string_list(value, name, count=256, length=256):
    if not isinstance(value, (list, tuple)) or len(value) > count:
        raise SafeError(name + " must be a bounded list of strings")
    if any(not isinstance(x, str) or not x.strip() or len(x) > length for x in value):
        raise SafeError(name + " contains an invalid or oversized string")
    return [x.strip() for x in value]


def number(value, name, low=0, high=100):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise SafeError(name + " must be a finite number")
    # Range checking works for arbitrary-size JSON integers without float conversion.
    if not low <= value <= high or (isinstance(value, float) and not math.isfinite(value)):
        raise SafeError(name + " must be between %s and %s" % (low, high))
    return value


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SafeError(name + " must be an integer between %d and %d" % (low, high))
    return value


EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]{1,64}@[\w.-]{1,190}\.[a-z]{2,24}\b")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{5,30}\d)(?!\w)")


def redact(value):
    text = EMAIL.sub("[email redacted]", str(value))
    return PHONE.sub(lambda m: "[phone redacted]" if sum(c.isdigit() for c in m[0]) >= 7 else m[0], text)


def report_data(value):
    if isinstance(value, dict):
        return {safe_text(k): (review_url(v) if k == 'url' and isinstance(v, str)
                              else report_data(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [report_data(v) for v in value]
    if isinstance(value, str):
        return safe_text(redact(value), MAX_CELL)
    return value


def review_url(value):
    """Preserve public provenance URLs exactly; refuse credentials/contact params."""
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() or
            unicodedata.category(c).startswith("C") for c in value):
        raise SafeError("invalid review URL")
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise SafeError("review URL needs an HTTP(S) host without credentials")
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise SafeError("invalid review URL port")
        if any(c in value for c in '<>"`\\'):
            raise SafeError("invalid review URL characters")
        sensitive = {'key', 'apikey', 'auth', 'authorization', 'password', 'passwd',
                     'session', 'sessionid', 'code', 'signature', 'sig', 'email', 'phone'}
        if EMAIL.search(unquote(parts.path)):
            raise SafeError('review URL path contains contact information; use a public source URL')
        for component in (parts.query, parts.fragment):
            decoded = unquote(component)
            if EMAIL.search(decoded):
                raise SafeError('review URL contains contact information; use a public source URL')
            for key, val in parse_qsl(component, keep_blank_values=True, max_num_fields=64):
                key = re.sub(r'[^a-z0-9]', '', key.lower())
                if key in sensitive or any(x in key for x in ('token', 'secret', 'credential')):
                    raise SafeError('review URL contains credential parameters; use a public source URL')
                if any(unicodedata.category(c).startswith('C') for c in key + val):
                    raise SafeError('review URL contains encoded control characters')
        return value
    except ValueError:
        raise SafeError("invalid review URL") from None


def diagnostic(tool, exc):
    # Do not include raw payloads, source lines or paths from parser exceptions.
    message = str(exc) if isinstance(exc, SafeError) else "invalid input or inaccessible local path"
    print(tool + ": " + safe_text(message, 240), file=sys.stderr)
    return 2
