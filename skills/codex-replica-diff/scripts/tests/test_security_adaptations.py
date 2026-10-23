# Derived from replica-skill tests: Copyright (c) 2026 Jake Schincariol, MIT. See ../../LICENSE.
"""Synthetic security regressions against the adapted tools, never upstream code."""
import contextlib
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

from _load import skill_directory, load as load_tool


def load(folder, name):
    return load_tool('replica-' + folder, name)


sweep = load('brand', 'sweep')
contrast = load('design', 'contrast')
imgdiff = load('diff', 'imgdiff')
parity = load('diff', 'parity')
reviews = load('entrepreneur', 'reviews')
listing = load('launch', 'listing')
safeio = sys.modules['_safeio']


def png_chunk(kind, body):
    return (struct.pack('>I', len(body)) + kind + body +
            struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff))


def png(width=1, height=1, raw=b'\0\0\0\0', color=2, depth=8, extra=b'', interlace=0):
    return (imgdiff.SIG + png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height,
            depth, color, 0, 0, interlace)) + extra +
            png_chunk(b'IDAT', zlib.compress(raw)) + png_chunk(b'IEND', b''))


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, data):
        path = self.root / name
        if isinstance(data, str):
            path.write_text(data)
        else:
            path.write_bytes(data)
        return path

    def invoke(self, module, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = module.main([os.fspath(x) for x in argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_read_and_write_refuse_link_and_special_files(self):
        target = self.put('target', 'private')
        link = self.root / 'sym'
        link.symlink_to(target)
        hard = self.root / 'hard'
        os.link(target, hard)
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        for path in (target, link, hard, fifo):
            with self.subTest(path=path.name), self.assertRaises(safeio.SafeError):
                safeio.read_bytes(path)
        for path in (target, link, hard, fifo):
            with self.subTest(output=path.name), self.assertRaises((safeio.SafeError, OSError)):
                safeio.write_new(path, b'changed')
        self.assertEqual(target.read_text(), 'private')

    def test_parent_directory_symlink_is_not_traversed(self):
        real = self.root / 'real'
        real.mkdir()
        (real / 'input').write_text('content')
        alias = self.root / 'alias'
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises((safeio.SafeError, OSError)):
            safeio.read_bytes(alias / 'input')
        with self.assertRaises((safeio.SafeError, OSError)):
            safeio.write_new(alias / 'output', b'changed')
        self.assertFalse((real / 'output').exists())

    def test_regular_output_is_private_and_no_overwrite(self):
        output = self.root / 'output'
        safeio.write_new(output, b'first')
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(safeio.SafeError):
            safeio.write_new(output, b'second')
        self.assertEqual(output.read_bytes(), b'first')

    def test_json_bounds_nonfinite_duplicate_and_nested(self):
        bad = [b'{"a":NaN}', b'{"a":1,"a":2}', b'[' * 25 + b'0' + b']' * 25,
               json.dumps({'s': 'x' * 16385}).encode(), b' ' * (safeio.MAX_JSON + 1)]
        for index, raw in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(safeio.SafeError):
                safeio.load_json(self.put('bad.json', raw))

    def test_csv_mismatched_duplicate_oversize_and_rows(self):
        bad = ['feature,priority,clone\nx,must,yes,extra\n',
               'feature,FEATURE,priority,clone\nx,y,must,yes\n',
               'feature,priority,clone\n' + 'x' * 16385 + ',must,yes\n',
               'feature,priority,clone\n' + 'x,must,yes\n' * 10001]
        for index, text in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(safeio.SafeError):
                parity.load(self.put('matrix.csv', text))

    def test_csv_formula_is_text_not_executed(self):
        path = self.put('formula.csv', 'feature,priority,clone\n=1+1,must,no\n')
        self.assertEqual(parity.score(parity.load(path))['missing'][0]['feature'], '=1+1')

    def test_sweep_omits_source_snippets_and_secret_files(self):
        self.put('app.txt', 'Reference SECRET_12345\n')
        self.put('.env', 'Reference PRIVATE_KEY=sekret\n')
        self.put('key.pem', 'Reference private\n')
        self.put('Reference\x1b[2J.txt', 'Reference\n')
        hits = sweep.sweep(self.root, avoid=['Reference'])
        encoded = json.dumps(hits)
        self.assertNotIn('SECRET_12345', encoded)
        self.assertNotIn('PRIVATE_KEY', encoded)
        self.assertNotIn('.env', encoded)
        self.assertNotIn('key.pem', encoded)
        self.assertTrue(all(set(h) == {'file', 'line', 'kind', 'match'} for h in hits))
        self.assertNotIn('\x1b', sweep.render(hits))

    def test_sweep_refuses_missing_empty_links_and_fifo(self):
        self.assertEqual(self.invoke(sweep, [self.root / 'missing', '--avoid', 'X'])[0], 2)
        self.assertEqual(self.invoke(sweep, [self.root, '--avoid', 'X'])[0], 2)
        self.put('empty.txt', '')
        self.assertEqual(self.invoke(sweep, [self.root, '--avoid', 'X'])[0], 2)
        self.put('safe.txt', 'safe')
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        self.assertEqual(self.invoke(sweep, [self.root, '--avoid', 'X'])[0], 2)
        fifo.unlink()
        (self.root / 'link').symlink_to(self.root / 'safe.txt')
        self.assertEqual(self.invoke(sweep, [self.root, '--avoid', 'X'])[0], 2)

    def test_contrast_malformed_pairs_fail_closed(self):
        for pairs in ([], [[]], [['text']], [['text', 'bg', 'typo']], [None], 'text'):
            path = self.put('tokens.json', json.dumps({'colors': {'text': '#111', 'bg': '#fff'},
                                                     'pairs': pairs}))
            self.assertEqual(self.invoke(contrast, [path])[0], 2, pairs)
        data = {'colors': {'text': '#111', 'bg': '#fff'}, 'pairs': [['text', 'bg']]}
        self.assertEqual(self.invoke(contrast, [self.put('valid.json', json.dumps(data))])[0], 0)

    def test_contrast_pair_budget_and_token_escapes(self):
        cols = {'text-' + str(i): '#111' for i in range(65)}
        cols.update({'bg-' + str(i): '#fff' for i in range(65)})
        with self.assertRaises(safeio.SafeError):
            contrast.default_pairs(cols)
        rows = contrast.check({'text\x1b[2J': '#111', 'bg': '#fff'}, [['text\x1b[2J', 'bg']])
        self.assertNotIn('\x1b', contrast.render(rows))

    def test_parity_nonfinite_range_and_empty_baselines(self):
        matrix = self.put('matrix.csv', 'feature,priority,clone\nThing,must,yes\n')
        for value in ('NaN', float('nan'), float('inf'), -1, 101, True):
            path = self.put('visual.json', json.dumps({'score': value}))
            self.assertEqual(self.invoke(parity, [matrix, '--visual', path, '--fail-under', '80'])[0], 2)
        for raw in ('feature,priority,clone\n', 'feature,priority,clone\nx,must,skip\n',
                    'feature,priority,clone,original\nx,must,yes,no\n'):
            self.assertEqual(self.invoke(parity, [self.put('empty.csv', raw), '--fail-under', '0'])[0], 2)
        for threshold in ('nan', 'inf', '-1', '101'):
            self.assertEqual(self.invoke(parity, [matrix, '--fail-under', threshold])[0], 2)

    def test_parity_weighting_and_unknown_gate(self):
        matrix = self.put('matrix.csv', 'feature,priority,clone\na,must,yes\nb,should,partial\n')
        result = parity.score(parity.load(matrix))
        self.assertEqual(result['feature_score'], 80)
        matrix = self.put('matrix.csv', 'feature,priority,clone\na,must,yes\nb,urgent,maybe\n')
        self.assertEqual(self.invoke(parity, [matrix, '--fail-under', '1'])[0], 1)
        self.assertEqual(self.invoke(parity, [matrix])[0], 0)

    def test_huge_json_integer_is_bounded_without_float_overflow(self):
        path = self.put('huge.json', '{"score":' + '1' * 401 + '}')
        with self.assertRaises(safeio.SafeError):
            parity.visual_scores([path])
        matrix = self.put('matrix.csv', 'feature,priority,clone,original\nThing,must,yes,yes\n')
        code, _, stderr = self.invoke(parity, [matrix, '--visual', path])
        self.assertEqual(code, 2)
        self.assertNotIn('Traceback', stderr)

    def test_parity_unknown_original_and_missing_column_are_not_ready(self):
        matrix = self.put('matrix.csv', 'feature,priority,clone,original\na,must,yes,yes\nb,must,yes,unknown\n')
        result = parity.score(parity.load(matrix))
        self.assertEqual(result['feature_score'], 100)
        self.assertEqual(result['counted'], 1)
        self.assertEqual(len(result['unknowns']), 1)
        self.assertIn('Unverified original features', parity.render(parity.combine(result, [])))
        self.assertEqual(self.invoke(parity, [matrix, '--fail-under', '0'])[0], 1)
        for original in ('unknown', ''):
            only = self.put('unknown.csv', 'feature,priority,clone,original\na,must,yes,' + original + '\n')
            self.assertEqual(self.invoke(parity, [only])[0], 2)
        typo = self.put('typo.csv', 'feature,priority,clone,original\na,must,yes,yess\n')
        self.assertEqual(self.invoke(parity, [typo])[0], 2)
        missing = self.put('missing.csv', 'feature,priority,clone\na,must,yes\n')
        planning = parity.score(parity.load(missing))
        self.assertEqual(planning['feature_score'], 100)
        self.assertTrue(planning['assumed_original'])
        self.assertIn('column absent', ' '.join(planning['problems']))
        self.assertEqual(self.invoke(parity, [missing, '--fail-under', '0'])[0], 1)

    def test_reviews_literals_not_regex_and_contact_redaction(self):
        themes = {'match_mode': 'literal', 'themes': [{'id': 'custom', 'label': 'Custom',
            'patterns': ['(a+)+$']}], 'request_patterns': ['please add']}
        path = self.put('themes.json', json.dumps(themes))
        loaded, req = reviews.load_themes(path)
        self.assertIsNone(loaded[0]['patterns'][0].search('a' * 1000 + '!'))
        self.assertIsNotNone(loaded[0]['patterns'][0].search('literal (a+)+$'))
        themes.pop('match_mode')
        with self.assertRaises(safeio.SafeError):
            reviews.load_themes(self.put('unsafe.json', json.dumps(themes)))
        csv_path = self.root / 'reviews.csv'
        with csv_path.open('w', newline='') as fh:
            writer = csv.writer(fh)
            writer.writerow(('source', 'url', 'rating', 'text'))
            writer.writerow(('forum\x1b[2J', 'https://example.test/review?id=123#comment-42', '1',
                             'Please add export. Contact me at me@example.test or +1 (415) 555-1234.'))
        code, stdout, stderr = self.invoke(reviews, [csv_path, '--json'])
        self.assertEqual(code, 0, stderr)
        self.assertNotIn('me@example.test', stdout)
        self.assertNotIn('555-1234', stdout)
        self.assertNotIn('\x1b', stdout)
        self.assertNotIn('?email', stdout)
        self.assertIn('redacted', stdout)
        self.assertEqual(self.invoke(reviews, [csv_path, '--out', csv_path])[0], 2)

    def test_reviews_preserve_public_url_and_refuse_credential_tokens(self):
        public = 'https://example.test/review?id=123#comment-42'
        numeric_id = 'https://example.test/review/123456789?id=123456789'
        self.assertEqual(safeio.review_url(public), public)
        self.assertEqual(safeio.report_data({'url': numeric_id})['url'], numeric_id)
        for suffix in ('?token=secret', '?access_token=secret', '?api_key=secret',
                       '?email=me%40example.test', '#access_token=secret'):
            with self.subTest(suffix=suffix), self.assertRaises(safeio.SafeError):
                safeio.review_url('https://example.test/review' + suffix)
        rows = self.put('urls.csv', 'url,text\n' + public + ',Too expensive\n' +
                        'https://example.test/review?token=secret,Too slow\n')
        code, stdout, stderr = self.invoke(reviews, [rows, '--json'])
        self.assertEqual(code, 0, stderr)
        self.assertIn(public, stdout)
        self.assertNotIn('token=secret', stdout)
        self.assertEqual(json.loads(stdout)['dropped'], 1)

    def test_listing_shapes_large_fields_and_terminal_controls(self):
        path = self.put('listing.json', json.dumps({'app_store': {'name': 4}}))
        self.assertEqual(self.invoke(listing, [path])[0], 2)
        data = {'app_store': {'name': 'App', 'description': 'Useful app',
                             'keywords': 'term\x1b[2J,term\x1b[2J'}}
        code, stdout, _ = self.invoke(listing, [self.put('listing.json', json.dumps(data))])
        self.assertEqual(code, 0)
        self.assertNotIn('\x1b', stdout)
        data['app_store']['description'] = 'x' * 16385
        self.assertEqual(self.invoke(listing, [self.put('listing.json', json.dumps(data))])[0], 2)

    def test_png_limits_before_inflate_and_truncated_crc(self):
        bad = [png(width=4000001), png(width=0), png(width=2000, height=2001),
               png(color=2, depth=4), png(interlace=1), png()[:-3]]
        corrupt = bytearray(png())
        corrupt[-1] ^= 1
        bad.append(bytes(corrupt))
        for index, raw in enumerate(bad):
            with self.subTest(index=index):
                path = self.put('bad.png', raw)
                self.assertEqual(self.invoke(imgdiff, [path, path])[0], 2)
        oversized = self.put('huge.png', png(width=2000, height=2001))
        with mock.patch.object(imgdiff.zlib, 'decompressobj', side_effect=AssertionError('must not inflate')):
            with self.assertRaises(safeio.SafeError):
                imgdiff.read_png(oversized)

    def test_png_bomb_bounded_length_palette_and_trailing(self):
        bad = [png(raw=b'\0' * 200000), png(raw=b'\0'), png() + b'trailing',
               png(color=3, raw=b'\0\1', extra=png_chunk(b'PLTE', b'\0\0\0')),
               png(extra=png_chunk(b'acTL', b'\0' * 8))]
        for index, raw in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(safeio.SafeError):
                imgdiff.read_png(self.put('bad.png', raw))

    def test_png_transparency_native_16bit_and_roundtrip(self):
        # Exact 16-bit transparent sample must not accidentally match another low byte.
        raw = b'\0\x12\x34\xab\xcd\xef\x01'
        extra = png_chunk(b'tRNS', b'\x12\x34\xab\xcd\xef\x01')
        image = imgdiff.read_png(self.put('transparent.png', png(raw=raw, depth=16, extra=extra)))
        self.assertEqual(image[2][0][0], (255, 255, 255))
        extra = png_chunk(b'tRNS', b'\x12\x35\xab\xcd\xef\x01')
        image = imgdiff.read_png(self.put('opaque.png', png(raw=raw, depth=16, extra=extra)))
        self.assertEqual(image[2][0][0], (0x12, 0xab, 0xef))
        path = self.root / 'roundtrip.png'
        imgdiff.write_png(path, *image)
        self.assertEqual(imgdiff.read_png(path), image)
        with self.assertRaises(safeio.SafeError):
            imgdiff.write_png(path, *image)

    def test_png_blank_layout_has_no_baseline_but_pixel_evaluates(self):
        path = self.put('blank.png', png())
        self.assertEqual(self.invoke(imgdiff, [path, path, '--fail-under', '0'])[0], 2)
        self.assertEqual(self.invoke(imgdiff, [path, path, '--mode', 'pixel', '--fail-under', '99'])[0], 0)
        for flag, value in (('--width', '0'), ('--cols', '0'), ('--cols', '257'),
                            ('--tolerance', '-1'), ('--fail-under', 'nan')):
            self.assertEqual(self.invoke(imgdiff, [path, path, flag, value])[0], 2)

    def test_isolated_cli_all_six_and_sanitized_argument_errors(self):
        # Execute only generated adapters, in isolated Python with no cwd/PYTHONPATH imports.
        matrix = self.put('matrix.csv', 'feature,priority,clone\nThing,must,yes\n')
        review_csv = self.put('review.csv', 'source,url,rating,text\nforum,https://example.test/r,1,Too expensive.\n')
        image = self.put('valid.png', png())
        scan = self.root / 'scan'
        scan.mkdir()
        (scan / 'app.txt').write_text('Useful app')
        commands = [
            ('brand', 'sweep', [str(scan), '--avoid', 'Reference']),
            ('design', 'contrast', ['#111', '#fff']),
            ('diff', 'imgdiff', [str(image), str(image), '--mode', 'pixel']),
            ('diff', 'parity', [str(matrix)]),
            ('entrepreneur', 'reviews', [str(review_csv), '--json']),
            ('launch', 'listing', [str(skill_directory('codex-replica-launch') / 'assets/listing.example.json')]),
        ]
        for folder, name, arguments in commands:
            script = skill_directory('codex-replica-' + folder) / 'scripts' / (name + '.py')
            result = subprocess.run([sys.executable, '-I', '-B', str(script)] + arguments,
                                    cwd=self.root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, (name, result.stderr))
            error = subprocess.run([sys.executable, '-I', '-B', str(script), '--bad\x1b[2J'],
                                   cwd=self.root, capture_output=True, text=True, timeout=10)
            self.assertEqual(error.returncode, 2)
            self.assertNotIn('\x1b', error.stderr)
            self.assertLess(len(error.stderr), 300)
            self.assertNotIn('Traceback', error.stderr)


if __name__ == '__main__':
    unittest.main()
