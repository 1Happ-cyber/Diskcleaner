"""扫描、内容查重及安全清理；不依赖图形界面。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
import hashlib
import json
import os
import stat
import time

# Windows 文件属性：重解析点（符号链接、目录联接等），扫描时不跟随。
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    mtime_ns: int
    device: int
    inode: int

    @property
    def suffix(self):
        """扩展名（小写）；无扩展名时返回占位符，供类型统计复用。"""
        return Path(self.path).suffix.lower() or '[无扩展名]'

    @classmethod
    def capture(cls, path):
        s = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(s.st_mode) or getattr(s, 'st_file_attributes', 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('不是普通文件或属于重解析点')
        return cls(str(path), s.st_size, s.st_mtime_ns, s.st_dev, s.st_ino)

    def verify(self):
        if FileRecord.capture(self.path) != self:
            raise ValueError('文件已变化，请重新扫描')


@dataclass
class ScanResult:
    root: str
    files: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    cancelled: bool = False

    @cached_property
    def total_size(self):
        # 扫描结果在界面渲染期间被多次读取，缓存避免每次都全量求和。
        return sum(f.size for f in self.files)

    @cached_property
    def type_sizes(self):
        result = {}
        for f in self.files:
            result[f.suffix] = result.get(f.suffix, 0) + f.size
        return result

    def largest(self, limit=100):
        return sorted(self.files, key=lambda f: (-f.size, f.path))[:limit]


class Scanner:
    PROGRESS_INTERVAL = 0.2  # 秒；同时按文件数节流，保证小目录也能看到进度

    def scan(self, root, cancel, progress=None):
        root = os.path.abspath(root)
        if not os.path.isdir(root) or os.path.islink(root) or os.path.isjunction(root):
            raise ValueError('请选择普通目录，不支持链接目录')
        result = ScanResult(root)
        pending = [root]
        total = 0
        last_report = 0.0
        while pending and not cancel.is_set():
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if cancel.is_set():
                            break
                        try:
                            s = entry.stat(follow_symlinks=False)
                            if entry.is_symlink() or getattr(s, 'st_file_attributes', 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                                continue
                            if stat.S_ISDIR(s.st_mode):
                                pending.append(entry.path)
                            elif stat.S_ISREG(s.st_mode):
                                record = FileRecord.capture(entry.path)
                                result.files.append(record)
                                total += record.size
                                if progress:
                                    now = time.monotonic()
                                    if len(result.files) % 100 == 0 or now - last_report >= self.PROGRESS_INTERVAL:
                                        last_report = now
                                        progress(len(result.files), total)
                        except (OSError, ValueError) as exc:
                            result.errors.append(f'{entry.path}: {exc}')
            except OSError as exc:
                result.errors.append(f'{directory}: {exc}')
        result.cancelled = cancel.is_set()
        if progress:
            progress(len(result.files), total)
        return result


class DuplicateFinder:
    def __init__(self, cache=None):
        self.cache = cache
        self.errors = []
        self.hashed = 0
        self.reused = 0

    def find(self, files, cancel, progress=None):
        self.errors = []
        self.hashed = 0
        self.reused = 0
        sizes = {}
        for record in files:
            sizes.setdefault(record.size, []).append(record)
        groups = []
        checked = 0
        for records in sizes.values():
            if len(records) < 2:
                continue
            hashes = {}
            for record in records:
                if cancel.is_set():
                    return []
                try:
                    record.verify()
                    digest_text = self.cache.lookup(record) if self.cache is not None else None
                    if digest_text:
                        # 大小与修改时间都没变，可直接复用上次的内容哈希。
                        self.reused += 1
                    else:
                        digest = hashlib.sha256()
                        with open(record.path, 'rb') as stream:
                            while chunk := stream.read(1024 * 1024):
                                if cancel.is_set():
                                    return []
                                digest.update(chunk)
                        digest_text = digest.hexdigest()
                        self.hashed += 1
                        if self.cache is not None:
                            self.cache.remember(record, digest_text)
                    record.verify()
                    hashes.setdefault(digest_text, []).append(record)
                except (OSError, ValueError) as exc:
                    self.errors.append(f'{record.path}: {exc}')
                checked += 1
                if progress:
                    progress(checked, self.hashed)
            for matched in hashes.values():
                # 同一物理文件的硬链接不视作可释放空间的重复副本。
                unique = {}
                for record in matched:
                    unique.setdefault((record.device, record.inode), record)
                if len(unique) > 1:
                    groups.append(list(unique.values()))
        return [] if cancel.is_set() else groups


class TrashBackend(ABC):
    @abstractmethod
    def trash(self, path):
        """只允许移入回收站；无法安全执行时抛出异常。"""


class SystemTrashBackend(TrashBackend):
    def trash(self, path):
        # 不使用 os.remove 或任何永久删除回退。
        from send2trash import send2trash
        send2trash(path)


class CleanupService:
    def __init__(self, trash, log_path):
        self.trash = trash
        self.log_path = Path(log_path)

    def clean(self, records, confirmed=False):
        if not confirmed:
            raise ValueError('必须明确确认后才能清理')
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        results = {}
        # 先打开日志，无法审计时拒绝清理。
        with self.log_path.open('a', encoding='utf-8') as log:
            for record in records:
                intent = {'time': time.time(), 'path': record.path, 'status': '准备移入回收站'}
                log.write(json.dumps(intent, ensure_ascii=False) + '\n')
                log.flush()
                os.fsync(log.fileno())
                try:
                    record.verify()
                    self.trash.trash(record.path)
                    status = '已移入回收站'
                except Exception as exc:
                    status = f'未清理：{exc}'
                results[record.path] = status
                log.write(json.dumps({**intent, 'status': status}, ensure_ascii=False) + '\n')
                log.flush()
                os.fsync(log.fileno())
        return results
