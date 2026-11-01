"""扫描快照、增量对比、哈希复用与历史摘要。

快照是"上次扫描时看到的样子"（路径、大小、修改时间、可选的内容哈希），
用于两件事：告诉用户本次扫描相对上次发生了什么，以及在查重时跳过未被修改
文件的重复读取。它不是文件系统级增量遍历，遍历成本仍然存在。
"""
from dataclasses import dataclass
import hashlib
import json
import os
import time
from pathlib import Path


def _key(path):
    return os.path.normcase(os.path.abspath(path))


@dataclass(frozen=True)
class Snapshot:
    root: str
    saved_at: str
    records: dict  # 路径 -> (size, mtime_ns, digest 或空串)

    def digest_for(self, record):
        entry = self.records.get(record.path)
        if not entry:
            return None
        size, mtime_ns, digest = entry
        if size == record.size and mtime_ns == record.mtime_ns and digest:
            return digest
        return None


@dataclass
class ChangeSet:
    added: list
    removed: list
    modified: list
    unchanged: int

    @property
    def changed(self):
        return len(self.added) + len(self.removed) + len(self.modified)

    def summary(self):
        return (f'较上次扫描：新增 {len(self.added)} 个，修改 {len(self.modified)} 个，'
                f'消失 {len(self.removed)} 个，未变 {self.unchanged} 个。')

    @classmethod
    def compare(cls, old, result):
        """对比快照与本次结果；旧快照为空时全部视为新增。"""
        current = {record.path: (record.size, record.mtime_ns) for record in result.files}
        if old is None:
            return cls(list(current), [], [], 0)
        previous = {path: (size, mtime_ns) for path, (size, mtime_ns, _) in old.records.items()}
        previous_by_key = {_key(path): (path, value) for path, value in previous.items()}
        current_by_key = {_key(path): (path, value) for path, value in current.items()}
        added = [current_by_key[key][0] for key in current_by_key.keys() - previous_by_key.keys()]
        removed = [previous_by_key[key][0] for key in previous_by_key.keys() - current_by_key.keys()]
        modified = [current_by_key[key][0] for key in current_by_key.keys() & previous_by_key.keys()
                    if current_by_key[key][1] != previous_by_key[key][1]]
        unchanged = len(current_by_key.keys() & previous_by_key.keys()) - len(modified)
        return cls(sorted(added), sorted(removed), sorted(modified), unchanged)


class SnapshotStore:
    """每个扫描根目录一份 JSON 快照，按路径哈希命名。"""

    def __init__(self, directory):
        self.directory = Path(directory)

    def path_for(self, root):
        digest = hashlib.sha1(_key(root).encode('utf-8')).hexdigest()
        return self.directory / f'{digest}.json'

    def load(self, root):
        path = self.path_for(root)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            records = {entry[0]: (int(entry[1]), int(entry[2]), entry[3] or '') for entry in data['records']}
            return Snapshot(data['root'], data['saved_at'], records)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return None

    def save(self, result, cache=None, saved_at=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        records = []
        for record in result.files:
            digest = cache.digest_for(record) if cache else ''
            records.append([record.path, record.size, record.mtime_ns, digest or ''])
        payload = {'root': result.root,
                   'saved_at': saved_at or time.strftime('%Y-%m-%d %H:%M:%S'),
                   'cancelled': result.cancelled,
                   'records': records}
        target = self.path_for(result.root)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, target)
        return target


class HashCache:
    """内容哈希缓存：只对大小与修改时间都未变的文件生效。"""

    def __init__(self):
        self._entries = {}

    @classmethod
    def from_snapshot(cls, snapshot):
        cache = cls()
        if snapshot:
            for path, (size, mtime_ns, digest) in snapshot.records.items():
                if digest:
                    cache._entries[_key(path)] = (size, mtime_ns, digest)
        return cache

    def digest_for(self, record):
        entry = self._entries.get(_key(record.path))
        if entry and entry[0] == record.size and entry[1] == record.mtime_ns:
            return entry[2]
        return None

    def lookup(self, record):
        """供 DuplicateFinder 调用的别名。"""
        return self.digest_for(record)

    def remember(self, record, digest):
        self._entries[_key(record.path)] = (record.size, record.mtime_ns, digest)

    def items(self):
        return dict(self._entries)

    def __len__(self):
        return len(self._entries)


class HistoryStore:
    """结构化扫描历史：每次扫描一行 JSON，读取时忽略损坏行。"""

    def __init__(self, path, limit=500):
        self.path = Path(path)
        self.limit = limit

    def append(self, entry):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def recent(self, count=50):
        if not self.path.exists():
            return []
        entries = []
        try:
            with self.path.open(encoding='utf-8') as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return entries
        return entries[-count:]

    def text(self, count=50):
        """把历史格式化成信息页可读的多行文本。"""
        lines = []
        for entry in reversed(self.recent(count)):
            change = entry.get('changes')
            detail = ''
            if isinstance(change, dict):
                detail = (f"；新增{change.get('added', 0)} 修改{change.get('modified', 0)} "
                          f"消失{change.get('removed', 0)}")
            reused = entry.get('reused')
            if reused:
                detail += f'；复用哈希{reused}'
            lines.append(f"{entry.get('time', '?')}  {entry.get('root', '?')}  "
                         f"{entry.get('count', 0)} 个文件 / {entry.get('bytes', 0)} 字节"
                         f"{'（已取消）' if entry.get('cancelled') else ''}"
                         f"；错误{entry.get('errors', 0)}{detail}")
        return lines or ['暂无扫描历史。']
