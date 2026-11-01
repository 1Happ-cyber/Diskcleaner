import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from diskcleaner.core import (FileRecord, Scanner, DuplicateFinder, CleanupService, TrashBackend)
from diskcleaner.history import HashCache


class FakeTrash(TrashBackend):
    def __init__(self, fail=False):
        self.paths = []
        self.fail = fail

    def trash(self, path):
        if self.fail:
            raise OSError('模拟回收站不可用')
        self.paths.append(path)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'a.txt').write_bytes(b'abc')
        (self.root / 'b.txt').write_bytes(b'abc')
        (self.root / 'c.bin').write_bytes(b'xyz')
        (self.root / 'sub').mkdir()
        (self.root / 'sub' / 'large').write_bytes(b'12345')
        self.cancel = threading.Event()

    def scan(self):
        return Scanner().scan(str(self.root), self.cancel)

    def test_statistics(self):
        result = self.scan()
        self.assertEqual(result.total_size, 14)
        self.assertEqual(result.type_sizes, {'.txt': 6, '.bin': 3, '[无扩展名]': 5})
        self.assertEqual(result.largest(1)[0].size, 5)

    def test_hash_not_only_size(self):
        groups = DuplicateFinder().find(self.scan().files, self.cancel)
        self.assertEqual(len(groups), 1)
        self.assertEqual({Path(f.path).name for f in groups[0]}, {'a.txt', 'b.txt'})

    def test_cancel(self):
        self.cancel.set()
        self.assertTrue(self.scan().cancelled)
        self.assertEqual(self.scan().files, [])
        self.assertEqual(DuplicateFinder().find([], self.cancel), [])

    def test_invalid_root(self):
        with self.assertRaises(ValueError):
            Scanner().scan(str(self.root / 'missing'), self.cancel)

    def test_permission_error(self):
        with patch('diskcleaner.core.os.scandir', side_effect=PermissionError('denied')):
            result = self.scan()
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.files, [])

    def test_confirmation_required(self):
        backend = FakeTrash()
        with self.assertRaises(ValueError):
            CleanupService(backend, self.root / 'log').clean(self.scan().files)
        self.assertEqual(backend.paths, [])

    def test_changed_file_refused(self):
        record = self.scan().largest(1)[0]
        Path(record.path).write_bytes(b'changed content')
        backend = FakeTrash()
        result = CleanupService(backend, self.root / 'log').clean([record], True)
        self.assertIn('未清理', result[record.path])
        self.assertEqual(backend.paths, [])

    def test_log_and_backend(self):
        record = self.scan().files[0]
        backend = FakeTrash()
        log = self.root / 'log'
        result = CleanupService(backend, log).clean([record], True)
        self.assertEqual(result[record.path], '已移入回收站')
        self.assertEqual(backend.paths, [record.path])
        self.assertEqual(len(log.read_text(encoding='utf-8').splitlines()), 2)

    def test_backend_failure(self):
        record = self.scan().files[0]
        result = CleanupService(FakeTrash(True), self.root / 'log').clean([record], True)
        self.assertIn('未清理', result[record.path])
        self.assertTrue(Path(record.path).exists())

    def test_unwritable_log_refuses_operation(self):
        backend = FakeTrash()
        records = self.scan().files
        with self.assertRaises(OSError):
            CleanupService(backend, self.root).clean(records, True)
        self.assertEqual(backend.paths, [])

    def test_changed_file_excluded_from_duplicates(self):
        records = self.scan().files
        (self.root / 'a.txt').write_bytes(b'new content')
        finder = DuplicateFinder()
        self.assertEqual(finder.find(records, self.cancel), [])
        self.assertEqual(len(finder.errors), 1)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as root:
            result = Scanner().scan(root, self.cancel)
            self.assertEqual(result.total_size, 0)
            self.assertEqual(result.type_sizes, {})

    def test_suffix_property(self):
        (self.root / 'UPPER.TXT').write_bytes(b'x')
        suffixes = {Path(record.path).name: record.suffix for record in self.scan().files}
        self.assertEqual(suffixes['UPPER.TXT'], '.txt')
        self.assertEqual(suffixes['large'], '[无扩展名]')

    def test_hardlink_not_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            first = Path(root) / 'a.bin'
            first.write_bytes(b'x' * 10)
            try:
                os.link(first, Path(root) / 'b.bin')
            except (OSError, NotImplementedError):
                self.skipTest('当前文件系统不支持硬链接')
            result = Scanner().scan(root, self.cancel)
            self.assertEqual(len(result.files), 2)
            self.assertEqual(DuplicateFinder().find(result.files, self.cancel), [])

    def test_empty_files_are_duplicates(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'e1.txt').write_bytes(b'')
            (Path(root) / 'e2.txt').write_bytes(b'')
            records = Scanner().scan(root, self.cancel).files
            groups = DuplicateFinder().find(records, self.cancel)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0][0].size, 0)

    def test_hash_cache_reused_on_second_run(self):
        records = self.scan().files
        cache = HashCache()
        first_finder = DuplicateFinder(cache)
        first = first_finder.find(records, self.cancel)
        self.assertGreaterEqual(len(first), 1)
        self.assertGreater(first_finder.hashed, 0)
        second_finder = DuplicateFinder(cache)
        second = second_finder.find(records, self.cancel)
        self.assertEqual(second, first)
        self.assertEqual(second_finder.hashed, 0)
        self.assertEqual(second_finder.reused, 3)  # a.txt、b.txt、c.bin 同为 3 字节

    def test_progress_reports_final_totals(self):
        calls = []
        result = Scanner().scan(str(self.root), self.cancel, lambda count, size: calls.append((count, size)))
        self.assertTrue(calls)
        self.assertEqual(calls[-1], (len(result.files), result.total_size))


if __name__ == '__main__':
    unittest.main()
