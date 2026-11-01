"""清理前的路径保护策略。

策略对象只回答"这个文件是否允许清理"，不负责界面确认、日志和回收站调用，
因此可以脱离界面单独测试，也可以在服务层复用。
"""
from abc import ABC, abstractmethod
import os


class PathPolicy(ABC):
    """路径策略契约。"""

    @abstractmethod
    def check(self, record):
        """允许时返回 None，拒绝时抛出 ValueError 并给出中文原因。"""

    def check_many(self, records):
        """批量检查；发现受保护路径时汇总后拒绝整批操作。"""
        blocked = []
        for record in records:
            try:
                self.check(record)
            except ValueError:
                blocked.append(record.path)
        if blocked:
            shown = '\n'.join(blocked[:5])
            more = f'\n……另有 {len(blocked) - 5} 个文件' if len(blocked) > 5 else ''
            raise ValueError(f'以下文件位于受保护的系统位置，已拒绝清理：\n{shown}{more}')


def _is_within(path, root):
    """Windows 路径的包含判断（大小写与短名不敏感）。"""
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(path)),
                                   os.path.normcase(os.path.abspath(root))]) == \
            os.path.normcase(os.path.abspath(root))
    except ValueError:  # 不同盘符
        return False


class ProtectedPathPolicy(PathPolicy):
    """拒绝清理系统目录与磁盘根目录下的文件，降低误删风险。"""

    def __init__(self, extra_roots=None, environ=None):
        environ = os.environ if environ is None else environ
        roots = ['SystemRoot', 'windir', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData', 'SystemDrive']
        self.roots = []
        for key in roots:
            value = environ.get(key)
            if value:
                self.roots.append(value)
        for extra in extra_roots or ():
            self.roots.append(extra)
        self.roots = [os.path.abspath(root) for root in self.roots]

    def check(self, record):
        for root in self.roots:
            if _is_within(record.path, root):
                raise ValueError(f'受保护的系统位置，拒绝清理：{record.path}')

    def describe(self):
        return [os.path.normcase(root) for root in self.roots]
