
# 磁盘空间分析与安全清理工具

面向对象方法学课程大作业，版本 **0.2.0**

## 快速开始（Windows）

1. 安装官方 Python **3.12 或以上**（保留 Tcl/Tk）。推荐 3.12/3.13，其他版本需实测依赖。
2. 双击 `start.bat`：自动选择 `py -3` / `python`，建立 `.venv`、安装依赖、启动程序。
3. 选择目录 → “扫描” → 查看大文件、类型分布、目录树与条形图。
4. “查找重复” → 查看分组 → “选择重复副本（每组保留一份）”或手动多选。
5. “清理选中” → 核对路径与数量 → 确认后移入回收站。
6. “打开回收站”核对，需要时恢复；下次扫描会显示“消失 N 个”。

手动运行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 测试与演示

```powershell
py -3 -m unittest discover -s tests -v
py -3 scripts/create_demo.py
```

第二条命令在系统临时目录生成演示样本：**5 个文件、1,050,976 字节、2 组重复**（其中一组为空文件），可直接用于界面扫描。测试中的回收站是模拟对象，不会删除用户文件。

回收站人工验收（只处理脚本自建的可丢弃样本）：

```powershell
.\.venv\Scripts\python.exe scripts\verify_recycle.py --dir .\验收样本 --open
```

界面截图（用真实扫描数据填充窗口后抓图）：

```powershell
.\.venv\Scripts\python.exe scripts\demo_screenshot.py
```

## 打包 exe

```powershell
build.bat
```

脚本依次安装依赖、执行 82 项测试、用 PyInstaller 打包；测试失败即停止。默认生成**目录版** `dist\DiskCleaner\DiskCleaner.exe`（连同 `_internal` 一起复制），压缩成 `dist\DiskCleaner-win64.zip` 后可在未安装 Python 的 Windows 机器解压即用。

> 打包注意：必须用**官方 Python**（python.org / scoop 等，自带 `tcl/`、`tk/` 目录）打包。用 Anaconda 的 Python 打包会出现 `ImportError: DLL load failed while importing _tkinter`，因为 PyInstaller 找不到 Anaconda 布局下的 Tcl/Tk。

## 数据与安全边界

- 扫描只读，不索取管理员权限；链接与重解析点跳过，权限异常记录后继续。
- 统计为文件**逻辑长度**之和，不等同于簇分配、压缩、稀疏文件的物理占用；硬链接副本不计入重复组。
- 历史 `%LOCALAPPDATA%/CourseDiskCleaner/history.jsonl`，快照 `snapshots/*.json`，清理日志 `cleanup.jsonl`；没有 `LOCALAPPDATA` 时退到用户主目录。默认目录不可写时（受限环境）自动回退到程序目录下的 `DiskCleanerData`，并在信息页注明实际位置。
- 清理前核对大小、修改时间、设备号、文件标识，并再次拒绝链接；文件变化则要求重新扫描。检查与操作之间仍存在竞争窗口，不适用于恶意并发修改路径的对抗环境。
- 只通过 Send2Trash 移入回收站，**没有任何永久删除的回退代码**；网络盘、移动盘、特殊文件系统受系统回收站限制，请先在可丢弃样本上验证恢复。
- 受保护路径（Windows、Program Files、ProgramData、系统盘根目录）拒绝清理；已知重复组禁止清理全部副本，并校验保留副本未变化。
- 清理不提供中途取消，以保证逐项审计；扫描/查重可取消，取消的扫描结果不允许清理。
- “增量对比”指与上次快照比较并复用未变文件的哈希，**不是**跳过目录遍历的文件系统级增量扫描。
- 百万级文件的界面性能与内存占用尚未验证；历史与快照尚无自动轮转。

