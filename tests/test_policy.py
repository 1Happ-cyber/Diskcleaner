import tempfile
import unittest
from pathlib import Path
from diskcleaner.core import FileRecord
from diskcleaner.policy import ProtectedPathPolicy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = self.root / 'Windows'
        (self.system / 'System32').mkdir(parents=True)
        (self.system / 'System32' / 'kernel.dll').write_bytes(b'x')
        (self.system / 'notepad.exe').write_bytes(b'x')
        self.safe = self.root / 'safe'
        self.safe.mkdir()
        (self.safe / 'mine.txt').write_bytes(b'abc')
        self.policy = ProtectedPathPolicy(extra_roots=[self.system],
                                          environ={'SystemRoot': str(self.system),
                                                   'ProgramFiles': str(self.root / 'Program Files')})

    def record(self, path):
        return FileRecord.capture(path)

    def test_blocks_system_file(self):
        with self.assertRaises(ValueError) as caught:
            self.policy.check(self.record(self.system / 'notepad.exe'))
        self.assertIn('受保护', str(caught.exception))

    def test_allows_user_file(self):
        self.assertIsNone(self.policy.check(self.record(self.safe / 'mine.txt')))

    def test_boundary_sibling_not_blocked(self):
        sibling = self.root / 'Windows2'
        sibling.mkdir()
        (sibling / 'a.txt').write_bytes(b'a')
        self.assertIsNone(self.policy.check(self.record(sibling / 'a.txt')))

    def test_case_insensitive(self):
        upper = str(self.system / 'NOTEPAD.EXE').upper()
        record = FileRecord(upper, 1, 0, 0, 0)
        with self.assertRaises(ValueError):
            self.policy.check(record)

    def test_check_many_reports_all_and_refuses(self):
        records = [self.record(self.system / 'notepad.exe'),
                   self.record(self.system / 'System32' / 'kernel.dll'),
                   self.record(self.safe / 'mine.txt')]
        with self.assertRaises(ValueError) as caught:
            self.policy.check_many(records)
        message = str(caught.exception)
        self.assertIn('notepad.exe', message)
        self.assertIn('kernel.dll', message)
        self.assertNotIn('mine.txt', message)

    def test_check_many_passes_when_safe(self):
        self.policy.check_many([self.record(self.safe / 'mine.txt')])

    def test_other_drive_is_outside(self):
        self.assertFalse(self.policy.check(FileRecord('X:\\data\\a.txt', 1, 0, 0, 0)))

    def test_describe_lists_roots(self):
        described = self.policy.describe()
        self.assertIn(str(self.system).lower(), described)


if __name__ == '__main__':
    unittest.main()
