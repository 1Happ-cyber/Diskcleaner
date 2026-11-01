"""扫描结果的只读分析器族。

所有分析器实现同一个 ``analyze(result) -> AnalysisReport`` 契约，界面只负责
渲染报告，不再自己计算统计口径。新增一种统计只需要新增一个 Analyzer 子类。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from pathlib import Path
from .formatting import human


@dataclass(frozen=True)
class Row:
    """一行展示数据；record 非空时表示该行对应一个可操作的文件。"""
    values: tuple
    record: object = None


@dataclass
class AnalysisReport:
    title: str
    columns: tuple
    rows: list = field(default_factory=list)
    note: str = ''


class Analyzer(ABC):
    """分析器抽象基类：统一职责与输出格式。"""
    title = ''
    columns = ()

    @abstractmethod
    def analyze(self, result):
        """返回 AnalysisReport；实现不得修改传入的 ScanResult。"""

    @staticmethod
    def percent(size, total):
        return f'{size / total:.1%}' if total else '0.0%'


class SizeRankingAnalyzer(Analyzer):
    title = '大文件排行（前100）'
    columns = ('大小', '路径')

    def __init__(self, limit=100):
        self.limit = max(1, int(limit))

    def analyze(self, result):
        rows = [Row((human(record.size), record.path), record) for record in result.largest(self.limit)]
        return AnalysisReport(self.title, self.columns, rows, f'按逻辑大小降序，最多 {self.limit} 项。')


class TypeAnalyzer(Analyzer):
    title = '文件类型分布'
    columns = ('类型', '大小', '占比')

    def analyze(self, result):
        total = result.total_size
        rows = [Row((suffix, human(size), self.percent(size, total)))
                for suffix, size in sorted(result.type_sizes.items(), key=lambda item: (-item[1], item[0]))]
        return AnalysisReport(self.title, self.columns, rows, '按扩展名归并，各行大小之和等于扫描总量。')


class DirectorySummary(Analyzer):
    """按扫描根目录的直属子目录汇总，根下文件单独列出；各项互不重叠。"""
    title = '直属子目录占用'
    columns = ('目录', '大小', '占比')

    def summarize(self, result):
        sizes = {}
        root = Path(result.root)
        for record in result.files:
            try:
                relative = Path(record.path).relative_to(root)
            except ValueError:
                continue
            key = relative.parts[0] + '/' if len(relative.parts) > 1 else '[根目录文件]'
            sizes[key] = sizes.get(key, 0) + record.size
        return sorted(sizes.items(), key=lambda item: (-item[1], item[0]))

    def analyze(self, result):
        total = result.total_size
        rows = [Row((name, human(size), self.percent(size, total))) for name, size in self.summarize(result)]
        return AnalysisReport(self.title, self.columns, rows, '一级汇总，不是任意深度的目录树。')


@dataclass(frozen=True)
class TreeNode:
    name: str
    path: str
    size: int
    files: int
    is_dir: bool


class DirectoryTree:
    """可逐层展开的目录树。

    ``build`` 一次遍历文件清单，把每个文件的大小沿路径向上累加到各级目录，
    因此 ``children(path)`` 可以按需展开而不必重复扫描。界面只在用户展开某个
    节点时调用它，避免一次性插入海量条目。
    """
    MAX_FILES_PER_NODE = 50
    MAX_CHILDREN = 500

    def __init__(self):
        self.root = ''
        self._sizes = {}
        self._counts = {}
        self._children = {}
        self._files = {}
        self.total_size = 0

    def build(self, result):
        self.__init__()
        self.root = os.path.abspath(result.root)
        self.total_size = result.total_size
        self._sizes = {self.root: 0}
        self._counts = {self.root: 0}
        self._children = {self.root: set()}
        self._files = {self.root: []}
        for record in result.files:
            directory = os.path.dirname(os.path.abspath(record.path))
            self._files.setdefault(directory, []).append(record)
            node = directory
            while node:
                self._sizes[node] = self._sizes.get(node, 0) + record.size
                self._counts[node] = self._counts.get(node, 0) + 1
                self._children.setdefault(node, set())
                if node == self.root:
                    break
                parent = os.path.dirname(node)
                if parent == node:  # 理论上不会发生：文件都在 root 之下
                    break
                self._children.setdefault(parent, set()).add(node)
                node = parent
        return self

    def children(self, directory):
        """返回目录节点：先按大小降序的子目录，再是本层文件（最多 MAX_FILES_PER_NODE 个）。"""
        directory = os.path.abspath(directory)
        found = [TreeNode(os.path.basename(path) or path, path, self._sizes.get(path, 0),
                          self._counts.get(path, 0), True)
                 for path in self._children.get(directory, ())]
        found.sort(key=lambda node: (-node.size, node.name))
        if len(found) > self.MAX_CHILDREN:
            hidden = found[self.MAX_CHILDREN:]
            found = found[:self.MAX_CHILDREN]
            found.append(TreeNode(f'……另 {len(hidden)} 个目录', '', 0, 0, True))
        records = sorted(self._files.get(directory, ()), key=lambda record: (-record.size, record.path))
        for record in records[:self.MAX_FILES_PER_NODE]:
            found.append(TreeNode(os.path.basename(record.path), record.path, record.size, 1, False))
        if len(records) > self.MAX_FILES_PER_NODE:
            rest = records[self.MAX_FILES_PER_NODE:]
            found.append(TreeNode(f'……另 {len(rest)} 个文件', '', 0, 0, False))
        return found

    def has_children(self, directory):
        return bool(self._children.get(os.path.abspath(directory))) or bool(self._files.get(os.path.abspath(directory)))
