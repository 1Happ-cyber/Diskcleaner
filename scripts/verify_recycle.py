"""回收站人工验收脚本。

用途：在**可丢弃**的临时文件中真实走一遍"移入回收站"链路，核对：
1. 依赖库可用；
2. 文件从原位置消失；
3. 审计日志先写"准备"再写"结果"；
4. **文件确实出现在回收站里**（只看"原文件消失"无法区分"移入回收站"和"被永久删除"）。

脚本只处理自己新建的样本，不触碰用户文件。验收后请在回收站恢复样本并核对内容，
再把结果填进 docs/测试记录.md。
"""
import argparse
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diskcleaner.core import CleanupService, FileRecord, SystemTrashBackend  # noqa: E402
from diskcleaner.diagnostics import missing_dependencies  # noqa: E402
from diskcleaner.shell import RecycleBinView  # noqa: E402

CONTENT = '可丢弃的验收样本。用于确认文件进入回收站后仍可恢复。\n'


def recent_dumps(seconds=120):
    """列出最近删除的回收站元数据（$I 文件）及其对应的内容文件（$R）。"""
    found = []
    now = time.time()
    for drive in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
        root = Path(f'{drive}:\\$Recycle.Bin')
        try:
            if not root.exists():
                continue
            metadata = list(root.rglob('$I*'))
        except OSError:
            continue
        for entry in metadata:
            try:
                if now - entry.stat().st_mtime > seconds:
                    continue
                payload = entry.with_name('$R' + entry.name[2:])
                if payload.exists():
                    found.append(payload)
            except OSError:
                continue
    return found


def confirm_in_bin(expected):
    """回收站里存在内容与样本一致的 $R 文件，才认为"移入回收站"成立。"""
    for payload in recent_dumps():
        try:
            if payload.read_bytes() == expected:
                return True, payload
        except OSError:
            continue
    return False, None


def main():
    parser = argparse.ArgumentParser(description='磁盘清理工具回收站验收')
    parser.add_argument('--open', action='store_true', help='验收后打开回收站')
    parser.add_argument('--dir', help='把样本放在指定目录并保留，便于在回收站中恢复核对')
    args = parser.parse_args()

    missing = missing_dependencies()
    if missing:
        print('无法验收：')
        for item in missing:
            print(f'  - {item}')
        print('请先执行：python -m pip install -r requirements.txt')
        return 2

    if args.dir:
        root = Path(args.dir).absolute()
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path(tempfile.mkdtemp(prefix='diskcleaner-recycle-'))
    sample = root / '待清理样本.txt'
    sample.write_text(CONTENT, encoding='utf-8')
    log = root / 'cleanup.jsonl'
    record = FileRecord.capture(sample)
    results = CleanupService(SystemTrashBackend(), log).clean([record], confirmed=True)
    status = results[record.path]
    print(f'样本目录：{root}（恢复文件后请手动删除）')
    print(f'样本路径：{record.path}')
    print(f'清理结果：{status}')
    print(f'审计日志：{log}')
    for line in log.read_text(encoding='utf-8').splitlines():
        print(f'  {line}')

    gone = not sample.exists()
    in_bin, payload = confirm_in_bin(CONTENT.encode('utf-8'))
    print(f'原位置是否已消失：{"是" if gone else "否"}')
    print(f'回收站中是否找到同内容样本：{"是" if in_bin else "否"}' + (f'（{payload}）' if in_bin else ''))
    if gone and status == '已移入回收站' and in_bin:
        print('\n验收通过。请打开回收站，恢复“待清理样本.txt”并核对内容，然后删除样本目录。')
        if args.open:
            RecycleBinView().open()
        return 0
    if gone and not in_bin:
        print('\n验收失败：原文件消失，但回收站里找不到样本，可能被永久删除或被环境拦截。')
        print('请在普通命令行（非受限/沙箱环境）重试；不要用重要文件做实验。')
        return 1
    print('\n验收失败：文件未被安全移入回收站，请保留上述输出用于排查。')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
