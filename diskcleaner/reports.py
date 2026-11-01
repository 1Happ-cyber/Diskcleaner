"""扫描结果的导出与重复副本选择策略。

统计口径已迁到 analyzers.py；这里保留 DirectorySummary 的再导出，避免旧调用
方（含既有测试）失效。
"""
import csv
from pathlib import Path
from .analyzers import DirectorySummary  # noqa: F401  （向后兼容的再导出）

__all__ = ['DirectorySummary', 'CsvExporter', 'DuplicateSelection']


class CsvExporter:
    def export(self, result, destination):
        """导出完整文件清单；独占创建，绝不覆盖已有文件。"""
        with Path(destination).open('x', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            writer.writerow(['路径', '逻辑大小（字节）', '修改时间（纳秒）', '扫描是否取消'])
            for record in result.files:
                path = record.path
                # 防止 Excel 把路径当公式执行。
                if path.startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
                    path = "'" + path
                writer.writerow([path, record.size, record.mtime_ns, result.cancelled])


class DuplicateSelection:
    def candidates(self, groups):
        """每组按路径排序保留第一份，仅返回建议，不执行删除。"""
        return [record for group in groups for record in sorted(group, key=lambda f: f.path)[1:]]

    def validate(self, groups, selected):
        """拒绝清空某个已知重复组，并确认被保留的副本仍然存在且未变化。"""
        selected_paths = {record.path for record in selected}
        for group in groups:
            if not any(record.path in selected_paths for record in group):
                continue
            retained = [record for record in group if record.path not in selected_paths]
            if not retained:
                raise ValueError('不允许清理已知重复组的全部副本，请至少保留一份。')
            for record in retained:
                record.verify()
