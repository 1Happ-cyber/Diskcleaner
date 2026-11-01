"""运行环境自检：只在缺少可选依赖时给出可读提示，不自动安装任何东西。"""
import platform


def missing_dependencies():
    """返回缺失依赖的中文说明列表；为空表示依赖齐全。"""
    missing = []
    try:
        import send2trash  # noqa: F401
    except ImportError:
        missing.append('send2trash：清理功能会把文件移入系统回收站，缺少该库时清理会被拒绝。')
    return missing


def environment():
    try:
        import tkinter
        tk_version = str(tkinter.TkVersion)
    except Exception:  # Tk 缺失时不影响纯命令行检查
        tk_version = '不可用'
    return {
        'python': platform.python_version(),
        'platform': platform.platform(),
        'tk': tk_version,
    }


def summary():
    info = environment()
    missing = missing_dependencies()
    lines = [f"Python {info['python']} / Tk {info['tk']} / {info['platform']}"]
    lines.extend(f'缺少依赖：{item}' for item in missing)
    lines.append('依赖检查通过。' if not missing else f'依赖检查：{len(missing)} 项缺失，清理前请安装依赖。')
    return lines
