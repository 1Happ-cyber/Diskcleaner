import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import tkinter as tk

from diskcleaner.core import DuplicateFinder, Scanner
from diskcleaner.gui import Application, CHART_TITLE, DUP_TITLE, LARGE_TITLE, TYPE_TITLE
from diskcleaner.history import ChangeSet
from diskcleaner.policy import ProtectedPathPolicy
from diskcleaner.reports import DuplicateSelection


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '样本 目录'
        (self.root / 'sub').mkdir(parents=True)
        (self.root / 'a.txt').write_bytes(b'abc')
        (self.root / 'b.txt').write_bytes(b'abc')
        (self.root / 'sub' / 'c.bin').write_bytes(b'12345')
        self.result = Scanner().scan(str(self.root), threading.Event())
        try:
            self.app = Application(data_dir=Path(self.temp.name) / 'data')
        except tk.TclError as exc:
            self.skipTest(f'没有可用的图形环境：{exc}')
        self.addCleanup(self.app.destroy)
        self.app.withdraw()
        self.app.dependencies = []
        self.app.changes = ChangeSet.compare(None, self.result)
        self.app.render_result(self.result)
        self.app.update_idletasks()

    def test_tables_are_filled(self):
        self.assertEqual(len(self.app.large.get_children()), 3)
        self.assertEqual(len(self.app.types.get_children()), 2)
        rows = self.app.large.get_children()
        records = [self.app.records[(LARGE_TITLE, row)] for row in rows]
        self.assertEqual(records[0].size, 5)
        self.assertEqual([record.size for record in records], [5, 3, 3])

    def test_summary_reports_totals_and_changes(self):
        status = self.app.status.get()
        self.assertIn('扫描完成', status)
        self.assertIn('3 个文件', status)
        self.assertIn('11.00 B', status)
        self.assertIn('新增 3', status)

    def test_tree_root_and_expand(self):
        root_item = self.app.tree_view.get_children()[0]
        self.assertEqual(self.app.tree_view.item(root_item, 'text'), self.result.root)
        names = [self.app.tree_view.item(child, 'text')
                 for child in self.app.tree_view.get_children(root_item)]
        self.assertIn('sub', names)
        sub_item = next(child for child in self.app.tree_view.get_children(root_item)
                        if self.app.tree_view.item(child, 'text') == 'sub')
        self.app.tree_view.focus(sub_item)
        self.app.on_tree_open(None)
        children = [self.app.tree_view.item(child, 'text')
                    for child in self.app.tree_view.get_children(sub_item)]
        self.assertIn('c.bin', children)
        self.assertNotIn('加载中……', children)

    def test_duplicate_selection(self):
        self.app.groups = DuplicateFinder().find(self.result.files, threading.Event())
        self.app.show_duplicates([], 0)
        self.assertEqual(len(self.app.dupes.get_children()), 2)
        self.app.select_duplicates()
        selected = self.app.dupes.selection()
        self.assertEqual(len(selected), 1)
        self.assertEqual(self.app.dupes.selection(), selected)
        chosen = self.app.records[(DUP_TITLE, selected[0])]
        self.assertIn(chosen.path, {record.path for record in DuplicateSelection().candidates(self.app.groups)})

    def test_chart_draws_bars(self):
        self.app.update_idletasks()
        self.app.draw_chart()
        self.assertGreater(len(self.app.chart.find_all()), 0)

    def test_clear_results_empties_everything(self):
        self.app.clear_results()
        self.assertIsNone(self.app.result)
        self.assertEqual(self.app.large.get_children(), ())
        self.assertEqual(self.app.tree_view.get_children(), ())
        self.assertEqual(self.app.chart.find_all(), ())

    def test_cancelled_scan_cannot_be_cleaned(self):
        self.app.result.cancelled = True
        self.app.large.selection_set(self.app.large.get_children()[0])
        with patch('diskcleaner.gui.messagebox.showwarning') as warning:
            self.app.clean()
        warning.assert_called_once()
        self.assertIn('部分扫描结果不允许清理', warning.call_args[0][1])

    def test_protected_path_blocks_clean(self):
        self.app.policy = ProtectedPathPolicy(extra_roots=[str(self.root)])
        self.app.large.selection_set(self.app.large.get_children()[0])
        with patch('diskcleaner.gui.messagebox.showwarning') as warning:
            self.app.clean()
        warning.assert_called_once()
        self.assertIn('受保护', warning.call_args[0][1])

    def test_missing_dependency_blocks_clean(self):
        self.app.dependencies = ['send2trash：模拟缺失']
        self.app.large.selection_set(self.app.large.get_children()[0])
        with patch('diskcleaner.gui.messagebox.showwarning') as warning:
            self.app.clean()
        warning.assert_called_once()
        self.assertEqual(warning.call_args[0][0], '缺少依赖')

    def test_tab_titles_match_tables(self):
        self.assertEqual(self.app.notebook.tab(self.app.tables[LARGE_TITLE].master, 'text'), LARGE_TITLE)
        self.assertEqual(self.app.notebook.tab(self.app.tables[TYPE_TITLE].master, 'text'), TYPE_TITLE)
        self.assertEqual(self.app.notebook.tab(self.app.tables[DUP_TITLE].master, 'text'), DUP_TITLE)
        self.assertEqual(self.app.notebook.tab(self.app.chart, 'text'), CHART_TITLE)


if __name__ == '__main__':
    unittest.main()
