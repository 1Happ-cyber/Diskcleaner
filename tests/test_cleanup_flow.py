import json
import tempfile
import threading
import unittest
from pathlib import Path
from diskcleaner.core import CleanupService, Scanner, TrashBackend


class RecordingTrash(TrashBackend):
    def __init__(self, fail_on=None):
        self.paths = []
        self.fail_on = fail_on

    def trash(self, path):
        if self.fail_on and Path(path).name == self.fail_on:
            raise OSError('模拟回收站不可用')
        self.paths.append(path)


class CleanupFlowTests(unittest.TestCase):
    """清理链路的集成测试：真实文件 + 模拟回收站 + 真实审计日志。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'a.txt').write_bytes(b'aaa')
        (self.root / 'b.txt').write_bytes(b'bbb')
        (self.root / 'c.txt').write_bytes(b'ccc')
        self.result = Scanner().scan(str(self.root), threading.Event())
        self.log = self.root / 'audit' / 'cleanup.jsonl'

    def records(self, *names):
        return [record for record in self.result.files if Path(record.path).name in names]

    def test_log_has_intent_and_result_per_file(self):
        backend = RecordingTrash()
        results = CleanupService(backend, self.log).clean(self.records('a.txt', 'b.txt'), confirmed=True)
        self.assertEqual(results[self.records('a.txt')[0].path], '已移入回收站')
        self.assertEqual(backend.paths, [record.path for record in self.records('a.txt', 'b.txt')])
        lines = [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(lines), 4)
        self.assertEqual([line['status'] for line in lines],
                         ['准备移入回收站', '已移入回收站'] * 2)
        self.assertEqual([Path(line['path']).name for line in lines], ['a.txt', 'a.txt', 'b.txt', 'b.txt'])

    def test_failure_is_isolated_to_one_file(self):
        backend = RecordingTrash(fail_on='b.txt')
        results = CleanupService(backend, self.log).clean(self.records('a.txt', 'b.txt', 'c.txt'), True)
        self.assertEqual(results[self.records('a.txt')[0].path], '已移入回收站')
        self.assertIn('未清理', results[self.records('b.txt')[0].path])
        self.assertEqual(results[self.records('c.txt')[0].path], '已移入回收站')
        self.assertEqual(len(backend.paths), 2)
        self.assertTrue((self.root / 'b.txt').exists())

    def test_refuses_without_confirmation_and_creates_no_log(self):
        backend = RecordingTrash()
        with self.assertRaises(ValueError):
            CleanupService(backend, self.log).clean(self.records('a.txt'))
        self.assertEqual(backend.paths, [])
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
