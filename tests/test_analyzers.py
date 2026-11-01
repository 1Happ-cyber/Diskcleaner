import os
import tempfile
import threading
import unittest
from pathlib import Path
from diskcleaner.analyzers import (AnalysisReport, Analyzer, DirectorySummary, DirectoryTree,
                                   SizeRankingAnalyzer, TypeAnalyzer)
from diskcleaner.core import Scanner


def scan(root):
    return Scanner().scan(str(root), threading.Event())


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'big.bin').write_bytes(b'1' * 100)
        (self.root / 'doc.txt').write_bytes(b'2' * 50)
        (self.root / 'sub').mkdir()
        (self.root / 'sub' / 'nested').mkdir()
        (self.root / 'sub' / 'nested' / 'deep.txt').write_bytes(b'3' * 10)
        self.result = scan(self.root)

    def test_size_ranking(self):
        report = SizeRankingAnalyzer(limit=2).analyze(self.result)
        self.assertIsInstance(report, AnalysisReport)
        self.assertEqual(len(report.rows), 2)
        self.assertEqual(report.rows[0].values[1], str(self.root / 'big.bin'))
        self.assertEqual(report.rows[0].record.path, str(self.root / 'big.bin'))

    def test_type_rows_and_ratio(self):
        report = TypeAnalyzer().analyze(self.result)
        rows = {row.values[0]: row for row in report.rows}
        self.assertEqual(rows['.bin'].values[2], f'{100 / 160:.1%}')
        self.assertEqual(rows['.txt'].values[1], '60.00 B')
        self.assertIsNone(rows['.bin'].record)  # 类型汇总行不绑定可清理文件

    def test_type_empty(self):
        self.result.files.clear()
        report = TypeAnalyzer().analyze(self.result)
        self.assertEqual(report.rows, [])

    def test_summary_one_level(self):
        items = dict(DirectorySummary().summarize(self.result))
        self.assertEqual(items, {'[根目录文件]': 150, 'sub/': 10})
        report = DirectorySummary().analyze(self.result)
        self.assertEqual({row.values[0] for row in report.rows}, {'[根目录文件]', 'sub/'})

    def test_tree_children_and_totals(self):
        tree = DirectoryTree().build(self.result)
        names = [node.name for node in tree.children(tree.root)]
        self.assertEqual(names, ['sub', 'big.bin', 'doc.txt'])  # 目录优先，再按大小降序排文件
        sizes = {node.name: node.size for node in tree.children(tree.root)}
        self.assertEqual(sizes['sub'], 10)
        nested = tree.children(str(self.root / 'sub'))
        self.assertEqual([(node.name, node.size) for node in nested], [('nested', 10)])
        deep = tree.children(str(self.root / 'sub' / 'nested'))
        self.assertEqual(deep[0].name, 'deep.txt')
        self.assertFalse(deep[0].is_dir)

    def test_tree_rebuild_resets_state(self):
        tree = DirectoryTree().build(self.result)
        tree.build(scan(self.root / 'sub'))
        self.assertEqual(tree.total_size, 10)
        self.assertEqual(tree.root, os.path.abspath(str(self.root / 'sub')))

    def test_analyzer_is_abstract(self):
        with self.assertRaises(TypeError):
            Analyzer()
        self.assertIsInstance(DirectorySummary(), Analyzer)

    def test_directory_summary_exported_from_reports(self):
        from diskcleaner.reports import DirectorySummary as Legacy
        self.assertIs(Legacy, DirectorySummary)


if __name__ == '__main__':
    unittest.main()
