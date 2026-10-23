# Derived from replica-skill tests: Copyright (c) 2026 Jake Schincariol, MIT. See ../../LICENSE.
"""Load adapted tools by SKILL.md name, independent of installation dir names."""
import functools
import importlib.util
import os
from pathlib import Path
import re
import stat

SKILLS_ROOT = Path(__file__).resolve().parents[3]
ROOT = str(Path(__file__).resolve().parent / 'fixtures')
ALLOWED = {('replica-brand', 'sweep'), ('replica-design', 'contrast'),
           ('replica-diff', 'imgdiff'), ('replica-diff', 'parity'),
           ('replica-entrepreneur', 'reviews'), ('replica-launch', 'listing')}


def _frontmatter_name(raw):
    """Read only our simple bounded scalar name, never evaluate YAML/content."""
    try:
        lines = raw.decode('utf-8-sig').splitlines()
    except UnicodeError:
        return None
    if not lines or lines[0] != '---':
        return None
    name = None
    for line in lines[1:257]:
        if line == '---':
            return name
        match = re.fullmatch(r'name:\s*[\"\']?([a-z0-9][a-z0-9-]{0,127})[\"\']?\s*', line)
        if match:
            if name is not None:
                return None
            name = match.group(1)
    return None


@functools.lru_cache(maxsize=1)
def _skill_locations():
    locations = {}
    root_fd = os.open(SKILLS_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with os.scandir(root_fd) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 4096:
                    raise ImportError('Maintenance skill discovery exceeds 4096 sibling entries.')
                if not entry.is_dir(follow_symlinks=False):
                    continue
                directory_fd = document_fd = None
                try:
                    directory_fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY |
                                           os.O_NOFOLLOW, dir_fd=root_fd)
                    document_fd = os.open('SKILL.md', os.O_RDONLY | os.O_NOFOLLOW |
                                          os.O_NONBLOCK, dir_fd=directory_fd)
                    info = os.fstat(document_fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
                        continue
                    with os.fdopen(document_fd, 'rb') as document:
                        document_fd = None
                        raw = document.read(65537)
                    if len(raw) > 65536:
                        continue
                    name = _frontmatter_name(raw)
                    if name is None:
                        continue
                    if name in locations:
                        raise ImportError('Duplicate installed skill name: ' + name)
                    locations[name] = SKILLS_ROOT / entry.name
                except OSError:
                    continue
                finally:
                    if document_fd is not None:
                        os.close(document_fd)
                    if directory_fd is not None:
                        os.close(directory_fd)
    finally:
        os.close(root_fd)
    return locations


def skill_directory(name):
    path = _skill_locations().get(name)
    if path is None:
        raise ImportError('Maintenance tests require installed skill "' + name +
                          '" beside this skill; install the complete Replica pack first.')
    return path


def load(folder, name):
    if (folder, name) not in ALLOWED:
        raise ValueError('not an adapted tool')
    path = skill_directory('codex-' + folder) / 'scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location('adapted_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
