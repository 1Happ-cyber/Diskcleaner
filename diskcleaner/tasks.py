"""后台任务调度：线程、取消事件与事件队列。

该类不导入 tkinter，界面只负责把事件渲染出来，因此可以在纯 unittest 中验证
"任务完成/失败/进度/取消"这些行为。
"""
import queue
import threading


class TaskRunner:
    """一次只运行一个后台任务，通过事件队列与调用方通信。"""

    def __init__(self):
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.kind = None
        self._thread = None

    def start(self, kind, operation):
        if self.busy:
            raise RuntimeError('已有任务在执行')
        self.kind = kind
        self.busy = True
        self.cancel.clear()

        def worker():
            try:
                self.events.put(('done', kind, operation()))
            except BaseException as exc:  # 后台线程必须把失败送回界面
                self.events.put(('error', kind, f'{type(exc).__name__}: {exc}'))
            finally:
                self.busy = False

        self._thread = threading.Thread(target=worker, name=f'diskcleaner-{kind}', daemon=True)
        self._thread.start()

    def progress(self, message):
        self.events.put(('progress', self.kind, message))

    def poll(self):
        """取出当前所有事件；done/error 会把 busy 置回 False。"""
        items = []
        while True:
            try:
                kind, task, payload = self.events.get_nowait()
            except queue.Empty:
                return items
            if kind in ('done', 'error'):
                self.busy = False
            items.append((kind, task, payload))

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)
        return not self.busy

    def reset(self):
        self.busy = False
        self.kind = None
        self.cancel.clear()
