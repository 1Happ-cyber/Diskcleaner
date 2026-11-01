"""与界面无关的显示格式化工具。"""


def human(size):
    """把字节数格式化为便于阅读的字符串。"""
    size = max(0, int(size))
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if size < 1024 or unit == 'TiB':
            return f'{size:.2f} {unit}'
        size /= 1024
    return f'{size:.2f} TiB'
