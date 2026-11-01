import csv
import tempfile
import threading
import unittest
from pathlib import Path
from diskcleaner.core import Scanner, DuplicateFinder
from diskcleaner.reports import DirectorySummary, CsvExporter, DuplicateSelection


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '子目录').mkdir()
        (self.root / 'a.txt').write_bytes(b'abc')
        (self.root / '子目录' / 'b.txt').write_bytes(b'abc')
        self.result = Scanner().scan(str(self.root), threading.Event())
        self.groups = DuplicateFinder().find(self.result.files, threading.Event())

    def test_directory_totals(self):
        items = dict(DirectorySummary().summarize(self.result))
        self.assertEqual(items, {'[根目录文件]': 3, '子目录/': 3})
        self.assertEqual(sum(items.values()), self.result.total_size)

    def test_csv_roundtrip(self):
        path = self.root / 'report.csv'
        CsvExporter().export(self.result, path)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(len(rows), 3)
        self.assertEqual({row[0] for row in rows[1:]}, {f.path for f in self.result.files})
        self.assertEqual(sum(int(row[1]) for row in rows[1:]), 6)

    def test_csv_refuses_overwrite(self):
        path = self.root / 'existing.csv'
        path.write_text('keep', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            CsvExporter().export(self.result, path)
        self.assertEqual(path.read_text(encoding='utf-8'), 'keep')

    def test_keep_one(self):
        policy = DuplicateSelection()
        selected = policy.candidates(self.groups)
        self.assertEqual(len(selected), 1)
        policy.validate(self.groups, selected)

    def test_all_copies_refused(self):
        with self.assertRaises(ValueError):
            DuplicateSelection().validate(self.groups, self.groups[0])

    def test_retained_copy_changed(self):
        policy = DuplicateSelection()
        selected = policy.candidates(self.groups)
        retained = next(f for f in self.groups[0] if f not in selected)
        Path(retained.path).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            policy.validate(self.groups, selected)

    def test_empty_summary(self):
        self.result.files.clear()
        self.assertEqual(DirectorySummary().summarize(self.result), [])
        self.assertEqual(DuplicateSelection().candidates([]), [])

    def test_csv_neutralises_formula_prefix(self):
        from diskcleaner.core import FileRecord, ScanResult
        result = ScanResult(root=str(self.root), files=[FileRecord('=cmd|x', 1, 0, 0, 0),
                                                        FileRecord('@sum', 2, 0, 0, 0)])
        path = self.root / 'formula.csv'
        CsvExporter().export(result, path)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual([row[0] for row in rows[1:]], ["'=cmd|x", "'@sum"])


if __name__ == '__main__':
    unittest.main()
