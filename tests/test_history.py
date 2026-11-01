import json
import tempfile
import threading
import unittest
from pathlib import Path
from diskcleaner.core import Scanner
from diskcleaner.history import ChangeSet, HashCache, HistoryStore, SnapshotStore


def scan(root):
    return Scanner().scan(str(root), threading.Event())


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'
        self.root.mkdir()
        (self.root / 'a.txt').write_bytes(b'abc')
        (self.root / 'b.txt').write_bytes(b'abc')
        self.store = SnapshotStore(Path(self.temp.name) / 'snapshots')
        self.result = scan(self.root)

    def test_roundtrip_with_digest(self):
        cache = HashCache()
        cache.remember(self.result.files[0], 'deadbeef')
        self.store.save(self.result, cache, saved_at='2026-01-01 00:00:00')
        snapshot = self.store.load(self.result.root)
        self.assertEqual(snapshot.root, self.result.root)
        self.assertEqual(snapshot.saved_at, '2026-01-01 00:00:00')
        self.assertEqual(snapshot.digest_for(self.result.files[0]), 'deadbeef')
        self.assertIsNone(snapshot.digest_for(self.result.files[1]))

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load(Path(self.temp.name) / 'missing'))

    def test_corrupt_snapshot_returns_none(self):
        target = self.store.path_for(self.result.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{not json', encoding='utf-8')
        self.assertIsNone(self.store.load(self.result.root))

    def test_save_leaves_no_temporary_file(self):
        self.store.save(self.result)
        self.assertEqual(list(self.store.directory.glob('*.tmp')), [])

    def test_snapshot_path_is_stable_per_root(self):
        self.assertEqual(self.store.path_for(self.result.root), self.store.path_for(self.root))
        self.assertNotEqual(self.store.path_for(self.result.root),
                            self.store.path_for(Path(self.temp.name)))


class ChangeSetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'
        self.root.mkdir()
        (self.root / 'keep.txt').write_bytes(b'keep')
        (self.root / 'edit.txt').write_bytes(b'old')
        (self.root / 'drop.txt').write_bytes(b'drop')
        self.result = scan(self.root)
        self.store = SnapshotStore(Path(self.temp.name) / 'snapshots')
        self.store.save(self.result)
        self.snapshot = self.store.load(self.result.root)

    def test_first_scan_marks_everything_added(self):
        changes = ChangeSet.compare(None, self.result)
        self.assertEqual(len(changes.added), 3)
        self.assertEqual(changes.unchanged, 0)

    def test_unchanged_detection(self):
        changes = ChangeSet.compare(self.snapshot, self.result)
        self.assertEqual(changes.changed, 0)
        self.assertEqual(changes.unchanged, 3)

    def test_added_modified_removed(self):
        (self.root / 'drop.txt').unlink()
        (self.root / 'edit.txt').write_bytes(b'changed')
        (self.root / 'new.txt').write_bytes(b'new')
        changes = ChangeSet.compare(self.snapshot, scan(self.root))
        self.assertEqual([Path(p).name for p in changes.added], ['new.txt'])
        self.assertEqual([Path(p).name for p in changes.removed], ['drop.txt'])
        self.assertEqual([Path(p).name for p in changes.modified], ['edit.txt'])
        self.assertEqual(changes.unchanged, 1)

    def test_summary_mentions_counts(self):
        changes = ChangeSet.compare(None, self.result)
        text = changes.summary()
        for word in ('新增 3', '修改 0', '消失 0', '未变 0'):
            self.assertIn(word, text)


class HashCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'a.bin').write_bytes(b'abc')
        self.result = scan(self.root)
        self.record = self.result.files[0]

    def test_lookup_requires_same_size_and_time(self):
        cache = HashCache()
        cache.remember(self.record, 'hash')
        self.assertEqual(cache.lookup(self.record), 'hash')
        (self.root / 'a.bin').write_bytes(b'changed size')
        changed = scan(self.root).files[0]
        self.assertIsNone(cache.lookup(changed))

    def test_from_snapshot_only_keeps_digests(self):
        cache = HashCache()
        self.assertIsNone(cache.lookup(self.record))
        store = SnapshotStore(Path(self.temp.name) / 'snap')
        cache.remember(self.record, 'hash')
        store.save(self.result, cache)
        restored = HashCache.from_snapshot(store.load(self.result.root))
        self.assertEqual(restored.lookup(self.record), 'hash')
        self.assertEqual(len(restored), 1)


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'history.jsonl'
        self.store = HistoryStore(self.path)

    def test_append_and_recent(self):
        self.store.append({'time': 't1', 'root': 'r1', 'count': 1, 'bytes': 2,
                           'cancelled': False, 'errors': 0})
        self.store.append({'time': 't2', 'root': 'r2', 'count': 2, 'bytes': 3,
                           'cancelled': True, 'errors': 1,
                           'changes': {'added': 1, 'modified': 0, 'removed': 0, 'unchanged': 5}})
        self.assertEqual(len(self.store.recent()), 2)
        self.assertEqual(self.store.recent(1)[0]['time'], 't2')

    def test_corrupt_line_is_skipped(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"time": "ok"}\nnot json\n', encoding='utf-8')
        recent = self.store.recent()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]['time'], 'ok')

    def test_text_summary_contains_flags(self):
        self.store.append({'time': 't', 'root': 'r', 'count': 2, 'bytes': 10,
                           'cancelled': True, 'errors': 1,
                           'changes': {'added': 1, 'modified': 2, 'removed': 3, 'unchanged': 4}})
        text = '\n'.join(self.store.text())
        self.assertIn('已取消', text)
        self.assertIn('新增1', text)

    def test_missing_file_gives_placeholder(self):
        self.assertEqual(self.store.text(), ['暂无扫描历史。'])


if __name__ == '__main__':
    unittest.main()
