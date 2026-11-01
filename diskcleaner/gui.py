"""Tkinter 界面：布局、事件绑定与结果渲染。

线程调度在 tasks.TaskRunner 中，统计口径在 analyzers 中，清理安全策略在
policy、history、reports 中；本模块只负责把事件画出来并把用户选择交给服务层。
"""
import os
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .analyzers import DirectorySummary, DirectoryTree, SizeRankingAnalyzer, TypeAnalyzer
from .core import CleanupService, DuplicateFinder, Scanner, SystemTrashBackend
from .diagnostics import missing_dependencies, summary
from .formatting import human
from .history import ChangeSet, HashCache, HistoryStore, SnapshotStore
from .policy import ProtectedPathPolicy
from .reports import CsvExporter, DuplicateSelection
from .shell import RecycleBinView
from .tasks import TaskRunner

LARGE_TITLE = '大文件排行（前100）'
TYPE_TITLE = '文件类型分布'
DUP_TITLE = '重复文件（手动选择）'
TREE_TITLE = '目录树'
CHART_TITLE = '空间条形图'
INFO_TITLE = '扫描与操作信息'


def pick_data_dir(preferred):
    """选择第一个可写的数据目录；受限环境（如只允许写工作区）下回退到程序目录。"""
    candidates = [Path(preferred), Path.cwd() / 'DiskCleanerData', Path.home() / 'DiskCleanerData']
    seen = set()
    for base in candidates:
        key = str(base).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / '.write_probe'
            probe.write_bytes(b'x')
            probe.unlink()
            return base, base != Path(preferred)
        except OSError:
            continue
    return Path(preferred), False


class Application(tk.Tk):
    def __init__(self, data_dir=None):
        super().__init__()
        self.title(f'磁盘占用分析与安全清理 · v{__version__}')
        self.geometry('1180x760')
        self.result = None
        self.groups = []
        self.tree = None
        self.changes = None
        self.cache = HashCache()
        self.runner = TaskRunner()
        self.policy = ProtectedPathPolicy()
        self.recycle = RecycleBinView()
        preferred = data_dir or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CourseDiskCleaner'
        self.data_dir, self.data_dir_fallback = pick_data_dir(preferred)
        self.history = HistoryStore(self.data_dir / 'history.jsonl')
        self.snapshots = SnapshotStore(self.data_dir / 'snapshots')
        self.records = {}
        self.node_paths = {}
        self.dependencies = []
        self.path = tk.StringVar(value=str(Path.home()))
        self.status = tk.StringVar(value='选择有权访问的目录开始扫描；不会自动清理任何文件。')
        self.build()
        self.report_dependencies()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    # ---------- 布局 ----------
    def build(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill='x')
        ttk.Entry(top, textvariable=self.path).pack(side='left', fill='x', expand=True)
        self.buttons = []
        for text, command in [('选择目录', self.choose), ('扫描', self.scan),
                              ('查找重复', self.duplicates), ('清理选中', self.clean)]:
            button = ttk.Button(top, text=text, command=command)
            button.pack(side='left', padx=3)
            self.buttons.append(button)
        ttk.Button(top, text='取消任务', command=self.runner.cancel.set).pack(side='left')

        actions = ttk.Frame(self, padding=(10, 0))
        actions.pack(fill='x')
        for text, command in [('选择重复副本（每组保留一份）', self.select_duplicates),
                              ('导出扫描 CSV', self.export_csv),
                              ('扫描历史', self.history_view),
                              ('打开回收站', self.open_recycle_bin)]:
            button = ttk.Button(actions, text=text, command=command)
            button.pack(side='left', padx=3)
            self.buttons.append(button)

        ttk.Label(self, textvariable=self.status, padding=10).pack(fill='x')
        self.bar = ttk.Progressbar(self, mode='indeterminate')

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        self.tables = {}

        self.large = self.table(LARGE_TITLE, ('大小', '路径'))
        self.types = self.table(TYPE_TITLE, ('类型', '大小', '占比'))
        self.tree_view = self.tree_table(TREE_TITLE)
        self.dupes = self.table(DUP_TITLE, ('组别', '大小', '路径'))
        self.chart = tk.Canvas(self.notebook, background='white', highlightthickness=0)
        self.notebook.add(self.chart, text=CHART_TITLE)
        self.chart.bind('<Configure>', lambda event: self.draw_chart())
        self.errors = tk.Text(self.notebook, wrap='word', state='disabled')
        self.notebook.add(self.errors, text=INFO_TITLE)
        self.tree_view.bind('<<TreeviewOpen>>', self.on_tree_open)

    def table(self, title, columns):
        frame = ttk.Frame(self.notebook)
        table = ttk.Treeview(frame, columns=columns, show='headings', selectmode='extended')
        for column in columns:
            table.heading(column, text=column)
            table.column(column, width=700 if column == '路径' else 150, minwidth=80)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=table.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=table.xview)
        table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        scroll.pack(side='right', fill='y')
        horizontal.pack(side='bottom', fill='x')
        table.pack(fill='both', expand=True)
        self.notebook.add(frame, text=title)
        self.tables[title] = table
        return table

    def tree_table(self, title):
        frame = ttk.Frame(self.notebook)
        table = ttk.Treeview(frame, columns=('大小', '占比', '文件数'), show='tree headings')
        table.heading('#0', text='目录 / 文件')
        table.heading('大小', text='大小')
        table.heading('占比', text='占比')
        table.heading('文件数', text='文件数')
        table.column('#0', width=620, minwidth=200)
        table.column('大小', width=120, anchor='e')
        table.column('占比', width=90, anchor='e')
        table.column('文件数', width=80, anchor='e')
        scroll = ttk.Scrollbar(frame, orient='vertical', command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        table.pack(fill='both', expand=True)
        self.notebook.add(frame, text=title)
        self.tables[title] = table
        return table

    # ---------- 依赖与状态 ----------
    def report_dependencies(self):
        self.dependencies = missing_dependencies()
        lines = ['依赖检查：'] + summary()
        lines.append(f'数据目录：{self.data_dir}' + ('（默认目录不可写，已回退到程序目录）'
                                                    if self.data_dir_fallback else ''))
        self.notes(lines)
        if self.dependencies:
            self.status.set('缺少依赖：' + '；'.join(self.dependencies))
        elif self.data_dir_fallback:
            self.status.set(f'数据目录已回退到 {self.data_dir}（默认目录不可写）。')

    def set_busy(self, busy):
        state = 'disabled' if busy else 'normal'
        for widget in self.buttons:
            widget.configure(state=state)
        if busy:
            self.bar.pack(fill='x', padx=10, before=self.notebook)
            self.bar.start()
        else:
            self.bar.stop()
            self.bar.pack_forget()

    def start(self, kind, operation):
        if self.runner.busy:
            return
        try:
            self.runner.start(kind, operation)
        except RuntimeError as exc:
            messagebox.showinfo('任务进行中', str(exc))
            return
        self.set_busy(True)
        self.status.set('任务进行中……')

    # ---------- 进度 ----------
    def report_scan_progress(self, count, size):
        self.runner.progress(f'正在扫描：已处理 {count} 个文件，逻辑大小 {human(size)}')

    def report_duplicate_progress(self, checked, hashed):
        self.runner.progress(f'正在查重：已检查 {checked} 个候选文件，实际读取 {hashed} 个')

    # ---------- 操作 ----------
    def choose(self):
        path = filedialog.askdirectory()
        if path:
            self.path.set(path)

    def scan(self):
        root = self.path.get()
        snapshots = self.snapshots

        def work():
            result = Scanner().scan(root, self.runner.cancel, self.report_scan_progress)
            old = snapshots.load(result.root)
            changes = ChangeSet.compare(old, result)
            cache = HashCache.from_snapshot(old)
            if not result.cancelled:
                try:
                    snapshots.save(result, cache)
                except OSError as exc:
                    result.errors.append(f'快照保存失败：{exc}')
            return result, changes, cache
        self.start('scan', work)

    def duplicates(self):
        if not self.result or self.result.cancelled:
            messagebox.showinfo('提示', '请先完成一次扫描。')
            return
        files = list(self.result.files)
        cache = self.cache
        result = self.result

        def work():
            finder = DuplicateFinder(cache)
            groups = finder.find(files, self.runner.cancel, self.report_duplicate_progress)
            if groups and not result.cancelled:
                try:
                    self.snapshots.save(result, cache)
                except OSError:
                    pass
            return groups, finder.errors, finder.reused
        self.start('duplicates', work)

    def clean(self):
        title, table = self.current_table()
        if table is None or table not in (self.large, self.dupes):
            messagebox.showinfo('提示', '请在大文件或重复文件页选择文件；按 Ctrl 可多选。')
            return
        selected = [self.records[(title, key)] for key in table.selection() if (title, key) in self.records]
        if not selected:
            messagebox.showinfo('提示', '请先选择要清理的文件。')
            return
        if self.result is None or self.result.cancelled:
            messagebox.showwarning('提示', '部分扫描结果不允许清理，请完成扫描。')
            return
        if self.dependencies:
            messagebox.showwarning('缺少依赖', '\n'.join(self.dependencies))
            return
        try:
            self.policy.check_many(selected)
            DuplicateSelection().validate(self.groups, selected)
        except (OSError, ValueError) as exc:
            messagebox.showwarning('清理前检查未通过', str(exc))
            return
        preview = '\n'.join(f.path for f in selected[:12])
        if len(selected) > 12:
            preview += f'\n……另有 {len(selected) - 12} 个文件'
        message = (f'将清理 {len(selected)} 个文件（{human(sum(f.size for f in selected))}）。\n'
                   f'已知重复组至少保留一份；未查重文件请自行确认用途。\n\n{preview}\n\n'
                   f'仅移入回收站，不永久删除；可在回收站恢复。是否继续？')
        if not messagebox.askyesno('确认移入回收站', message, default='no'):
            return
        service = CleanupService(SystemTrashBackend(), self.data_dir / 'cleanup.jsonl')
        groups = list(self.groups)

        def work():
            DuplicateSelection().validate(groups, selected)
            return service.clean(selected, confirmed=True)
        self.start('clean', work)

    def select_duplicates(self):
        if not self.groups:
            messagebox.showinfo('提示', '请先完成查重。')
            return
        paths = {record.path for record in DuplicateSelection().candidates(self.groups)}
        keys = [key for key in self.dupes.get_children()
                if (DUP_TITLE, key) in self.records and self.records[(DUP_TITLE, key)].path in paths]
        self.dupes.selection_set(keys)
        self.notebook.select(self.tables[DUP_TITLE].master)
        self.status.set(f'已建议选择 {len(keys)} 个副本，每组按路径排序保留第一份；请人工核对后清理。')

    def export_csv(self):
        if not self.result:
            messagebox.showinfo('提示', '请先扫描。')
            return
        destination = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV 文件', '*.csv')])
        if not destination:
            return
        result = self.result

        def work():
            if Path(destination).exists():
                raise ValueError('目标文件已存在，请另选文件名；为避免覆盖数据，程序不覆盖已有文件。')
            try:
                CsvExporter().export(result, destination)
            except FileExistsError:
                raise ValueError('目标文件已存在，请另选文件名。') from None
            return destination
        self.start('export', work)

    def history_view(self):
        try:
            lines = self.history.text(50)
        except OSError as exc:
            messagebox.showerror('历史读取失败', str(exc))
            return
        self.notes(['最近 50 次扫描摘要（不是文件快照）：'] + lines)
        self.notebook.select(self.errors)

    def open_recycle_bin(self):
        try:
            self.recycle.open()
            self.status.set('已打开系统回收站；可在其中核对与恢复被移入的文件。')
        except OSError as exc:
            messagebox.showerror('无法打开回收站', str(exc))

    # ---------- 渲染 ----------
    def current_table(self):
        widget = self.nametowidget(self.notebook.select())
        title = self.notebook.tab(widget, 'text')
        return title, self.tables.get(title)

    def fill_report(self, analyzer, table, title):
        report = analyzer.analyze(self.result)
        for row in report.rows:
            key = table.insert('', 'end', values=row.values)
            if row.record is not None:
                self.records[(title, key)] = row.record

    def render_result(self, result):
        self.result = result
        self.groups = []
        self.tree = DirectoryTree().build(result)
        self.records.clear()
        for table in (self.large, self.types, self.dupes):
            table.delete(*table.get_children())
        self.tree_view.delete(*self.tree_view.get_children())
        self.node_paths.clear()
        self.fill_report(SizeRankingAnalyzer(), self.large, LARGE_TITLE)
        self.fill_report(TypeAnalyzer(), self.types, TYPE_TITLE)
        self.fill_tree()
        self.draw_chart()
        self.notes(result.errors)
        suffix = self.changes.summary() if self.changes else ''
        self.status.set(f'{"已取消（部分结果）" if result.cancelled else "扫描完成"}：'
                        f'{len(result.files)} 个文件，{human(result.total_size)}，'
                        f'{len(result.errors)} 项错误；统计为逻辑大小。{suffix}')

    def fill_tree(self):
        if not self.tree or not self.result:
            return
        total = self.result.total_size or 1
        root_id = self.tree_view.insert(
            '', 'end', text=self.tree.root, open=True,
            values=(human(self.result.total_size), '100.0%', len(self.result.files)))
        self.node_paths[root_id] = self.tree.root
        self.expand_node(root_id, total)

    def expand_node(self, item, total):
        path = self.node_paths.get(item)
        if not path:
            return
        for node in self.tree.children(path):
            child = self.tree_view.insert(item, 'end', text=node.name,
                                           values=(human(node.size),
                                                   f'{node.size / total:.1%}' if total else '0.0%',
                                                   node.files))
            if node.path and node.is_dir:
                self.node_paths[child] = node.path
                self.tree_view.insert(child, 'end', text='加载中……')

    def on_tree_open(self, event):
        item = self.tree_view.focus()
        if item not in self.node_paths:
            return
        children = self.tree_view.get_children(item)
        if not any(self.tree_view.item(child, 'text') == '加载中……' for child in children):
            return
        for child in children:
            self.tree_view.delete(child)
        self.expand_node(item, self.result.total_size or 1)

    def draw_chart(self):
        self.chart.delete('all')
        if not self.result:
            return
        items = DirectorySummary().summarize(self.result)
        if len(items) > 12:
            items = items[:12] + [('[其余目录合计]', sum(size for _, size in items[12:]))]
        width = max(100, self.chart.winfo_width() - 340)
        total = self.result.total_size
        self.chart.create_text(16, 20, anchor='w', text='直属子目录递归占用（逻辑大小；取消扫描为部分结果）')
        for index, (name, size) in enumerate(items):
            y = 52 + index * 36
            ratio = size / total if total else 0
            label = name if len(name) <= 24 else name[:21] + '…'
            self.chart.create_text(16, y + 10, anchor='w', text=label)
            self.chart.create_rectangle(200, y, 200 + width * ratio, y + 22, fill='#3979b9', outline='')
            self.chart.create_text(210 + width * ratio, y + 10, anchor='w', text=f'{human(size)} ({ratio:.1%})')

    def notes(self, lines):
        self.errors.configure(state='normal')
        self.errors.delete('1.0', 'end')
        self.errors.insert('end', '\n'.join(lines) or '没有记录到错误。')
        self.errors.configure(state='disabled')

    def clear_results(self):
        self.result = None
        self.groups = []
        self.tree = None
        self.changes = None
        self.records.clear()
        self.node_paths.clear()
        for table in (self.large, self.types, self.dupes, self.tree_view):
            table.delete(*table.get_children())
        self.draw_chart()

    # ---------- 事件循环 ----------
    def poll(self):
        for kind, task, payload in self.runner.poll():
            if kind == 'progress':
                self.status.set(payload)
                continue
            self.set_busy(False)
            if kind == 'error':
                self.status.set('任务失败；如发生清理错误，请查看日志并重新扫描。')
                messagebox.showerror('任务失败', payload)
            elif task == 'scan':
                result, self.changes, self.cache = payload
                self.render_result(result)
                self.record_history(result)
            elif task == 'duplicates':
                self.groups = payload[0]
                self.show_duplicates(payload[1], payload[2])
            elif task == 'export':
                self.status.set(f'CSV 导出完成：{payload}（包含完整文件清单及扫描取消标记）')
            elif task == 'clean':
                self.notes([f'{path}: {status}' for path, status in payload.items()])
                self.clear_results()
                self.notebook.select(self.errors)
                self.status.set('清理操作结束，请查看逐项结果并重新扫描。')
        self.after(100, self.poll)

    def show_duplicates(self, errors, reused):
        self.dupes.delete(*self.dupes.get_children())
        self.records = {key: value for key, value in self.records.items() if key[0] != DUP_TITLE}
        for number, group in enumerate(self.groups, 1):
            for record in group:
                key = self.dupes.insert('', 'end', values=(number, human(record.size), record.path))
                self.records[(DUP_TITLE, key)] = record
        self.notes(errors)
        self.notebook.select(self.tables[DUP_TITLE].master)
        reused_text = f'；复用上次哈希 {reused} 个文件' if reused else ''
        self.status.set(f'发现 {len(self.groups)} 组内容重复文件{reused_text}；不会自动选择或删除。')

    def record_history(self, result):
        entry = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'root': result.root,
            'count': len(result.files),
            'bytes': result.total_size,
            'cancelled': result.cancelled,
            'errors': len(result.errors),
            'changes': {'added': len(self.changes.added), 'modified': len(self.changes.modified),
                        'removed': len(self.changes.removed), 'unchanged': self.changes.unchanged},
        }
        try:
            self.history.append(entry)
        except OSError as exc:
            messagebox.showwarning('历史保存失败', str(exc))

    def close(self):
        if self.runner.busy:
            messagebox.showinfo('任务进行中', '请取消扫描/查重并等待结束；清理操作请等待完成后关闭。')
            return
        self.destroy()


def main():
    Application().mainloop()
