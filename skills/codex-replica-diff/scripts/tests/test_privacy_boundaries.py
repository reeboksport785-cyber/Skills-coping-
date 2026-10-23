"""Run every helper with synthetic private data and blocked collection paths.

This is regression evidence for these invocations, not a production sandbox.
No real account, network destination or credential is used.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from _load import skill_directory
from test_security_adaptations import png


RUNNER = r'''
import os, runpy, sys

protected = {'OPENAI_API_KEY', 'GITHUB_TOKEN', 'AWS_SECRET_ACCESS_KEY', 'BOT_TOKEN'}

class PrivateEnvironment(dict):
    def __getitem__(self, key):
        if key in protected:
            raise RuntimeError('unexpected credential environment read')
        return super().__getitem__(key)
    def get(self, key, default=None):
        if key in protected:
            raise RuntimeError('unexpected credential environment read')
        return super().get(key, default)
    def items(self):
        raise RuntimeError('unexpected environment enumeration')
    def values(self):
        raise RuntimeError('unexpected environment enumeration')
    def copy(self):
        raise RuntimeError('unexpected environment copy')
    def __repr__(self):
        raise RuntimeError('unexpected environment display')

os.environ = PrivateEnvironment(os.environ)
forbidden_names = {'.env', 'credentials', 'credentials.json', 'id_ed25519',
                   '.ssh', '.aws', '.netrc'}

def guard(event, args):
    if event.startswith('socket.') or event in {
        'urllib.Request', 'subprocess.Popen', 'os.system', 'os.posix_spawn',
        'os.posix_spawnp', 'os.exec', 'os.fork', 'os.forkpty', 'pty.spawn'
    }:
        raise RuntimeError('unexpected network or subprocess operation')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.path.basename(os.fsdecode(args[0]))
        if name in forbidden_names or name.startswith('.env.'):
            raise RuntimeError('unexpected credential file read')

sys.addaudithook(guard)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''


class HelperPrivacyTests(unittest.TestCase):
    def test_all_helpers_without_credential_reads_network_or_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / 'home'
            home.mkdir(mode=0o700)
            marker = 'PRIVATE_CANARY_6a93d8e2'
            for name in ('.env', 'credentials.json', 'id_ed25519'):
                (home / name).write_text(marker)
            for name in ('.ssh', '.aws'):
                (home / name).mkdir(mode=0o700)
                (home / name / 'credentials').write_text(marker)
            scan = root / 'project'
            scan.mkdir()
            (scan / 'app.txt').write_text('Useful application')
            for name in ('.env', 'credentials.json'):
                (scan / name).write_text('Reference ' + marker)
            (root / 'matrix.csv').write_text(
                'feature,priority,original,clone\nThing,must,yes,yes\n')
            (root / 'reviews.csv').write_text(
                'source,url,rating,text\nforum,https://example.test/r,1,Too expensive.\n')
            (root / 'image.png').write_bytes(png())
            before = {p: p.read_bytes() for p in home.rglob('*') if p.is_file()}
            env = {'PATH': os.defpath, 'HOME': str(home), 'LANG': 'C.UTF-8',
                   **{key: marker for key in ('OPENAI_API_KEY', 'GITHUB_TOKEN',
                      'AWS_SECRET_ACCESS_KEY', 'BOT_TOKEN')}}
            commands = [
                ('brand', 'sweep', [str(scan), '--avoid', 'Reference']),
                ('design', 'contrast', ['#111', '#fff']),
                ('diff', 'imgdiff', [str(root / 'image.png'), str(root / 'image.png'),
                                     '--mode', 'pixel', '--out', str(root / 'diff.png')]),
                ('diff', 'parity', [str(root / 'matrix.csv')]),
                ('entrepreneur', 'reviews', [str(root / 'reviews.csv'),
                                             '--out', str(root / 'feedback.md')]),
                ('launch', 'listing', [str(skill_directory('codex-replica-launch') /
                                           'assets/listing.example.json')]),
            ]
            for folder, name, arguments in commands:
                with self.subTest(helper=name):
                    script = skill_directory('codex-replica-' + folder) / 'scripts' / (name + '.py')
                    result = subprocess.run(
                        [sys.executable, '-I', '-B', '-c', RUNNER, str(script), *arguments],
                        cwd=root, env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, (name, result.stderr))
                    self.assertNotIn(marker, result.stdout + result.stderr)
            self.assertEqual(before, {p: p.read_bytes() for p in home.rglob('*') if p.is_file()})
            for path in (root / 'feedback.md', root / 'diff.png'):
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(marker.encode(), path.read_bytes())


if __name__ == '__main__':
    unittest.main()
