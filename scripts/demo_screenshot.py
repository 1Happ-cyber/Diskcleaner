"""生成界面截图：用演示数据填充真实窗口并抓取为 PNG。

只用于课程报告配图，不修改任何真实文件。窗口内容的统计来自一次真实扫描。
用法：python scripts/demo_screenshot.py [--out docs/screenshot.png]
"""
import argparse
import ctypes
import struct
import sys
import threading
import time
import zlib
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diskcleaner.core import DuplicateFinder, Scanner  # noqa: E402
from diskcleaner.formatting import human  # noqa: E402
from diskcleaner.gui import Application  # noqa: E402
from diskcleaner.history import ChangeSet  # noqa: E402

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD),
                ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD),
                ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


def capture(hwnd, width, height):
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)
    if not user32.PrintWindow(hwnd, memory_dc, 2):
        user32.PrintWindow(hwnd, memory_dc, 0)
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height  # 负值表示自上而下
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(hwnd, window_dc)
    return buffer.raw


def write_png(path, width, height, bgra):
    rows = []
    for y in range(height):
        row = bgra[y * width * 4:(y + 1) * width * 4]
        rgb = bytearray()
        for x in range(0, len(row), 4):
            rgb += bytes((row[x + 2], row[x + 1], row[x]))
        rows.append(b'\x00' + bytes(rgb))
    raw = b''.join(rows)

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    png = (b'\x89PNG\r\n\x1a\n' +
           chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
           chunk(b'IDAT', zlib.compress(raw, 6)) +
           chunk(b'IEND', b''))
    path.write_bytes(png)


def make_demo(base):
    root = Path(base) / 'course-demo'
    (root / 'documents').mkdir(parents=True, exist_ok=True)
    (root / 'images').mkdir(parents=True, exist_ok=True)
    (root / 'videos').mkdir(parents=True, exist_ok=True)
    (root / 'documents' / 'notes.txt').write_bytes(b'course-demo\n' * 100)
    (root / 'documents' / 'notes-copy.txt').write_bytes(b'course-demo\n' * 100)
    (root / 'images' / 'sample.bin').write_bytes(bytes(range(256)) * 2048)
    (root / 'images' / 'sample-copy.bin').write_bytes(bytes(range(256)) * 2048)
    (root / 'videos' / 'clip.dat').write_bytes(b'v' * 300000)
    (root / 'readme.txt').write_bytes(b'hello')
    return root


def main():
    parser = argparse.ArgumentParser(description='界面截图生成器')
    parser.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'docs'))
    args = parser.parse_args()
    base = Path(__file__).resolve().parents[1] / 'demo-data'
    root = make_demo(base)
    app = Application(data_dir=base / 'data')
    app.withdraw()
    app.path.set(str(root))
    result = Scanner().scan(str(root), threading.Event())
    app.changes = ChangeSet.compare(None, result)
    app.render_result(result)
    app.groups = DuplicateFinder().find(result.files, threading.Event())
    app.show_duplicates([], 0)
    app.status.set(f'扫描完成：{len(result.files)} 个文件，{human(result.total_size)}；'
                   f'发现 {len(app.groups)} 组内容重复文件。统计为逻辑大小。')
    app.bar.pack_forget()
    app.geometry('1180x760+80+60')
    app.deiconify()
    app.update()
    app.after(300, app.update)
    time.sleep(0.4)
    app.update()

    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    targets = [(app.tables['大文件排行（前100）'].master, 'screenshot-large'),
               (app.tables['文件类型分布'].master, 'screenshot-types'),
               (app.tables['目录树'].master, 'screenshot-tree'),
               (app.tables['重复文件（手动选择）'].master, 'screenshot-duplicates')]
    for widget, name in targets:
        app.notebook.select(widget)
        if name == 'screenshot-tree':
            root_item = app.tree_view.get_children()[0]
            for child in app.tree_view.get_children(root_item):
                if app.tree_view.item(child, 'text') == 'images':
                    for stale in app.tree_view.get_children(child):
                        app.tree_view.delete(stale)
                    app.expand_node(child, app.result.total_size or 1)
                    app.tree_view.item(child, open=True)
                    break
        app.update()
        time.sleep(0.25)
        app.update()
        frame = int(app.wm_frame(), 16)
        rect = wintypes.RECT()
        user32.GetWindowRect(frame, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        pixels = capture(frame, width, height)
        target = output / f'{name}.png'
        write_png(target, width, height, pixels)
        print(f'已保存 {target}（{width}x{height}）')
    app.destroy()


if __name__ == '__main__':
    main()
