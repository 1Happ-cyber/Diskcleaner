"""系统外壳适配：打开回收站供用户核对与恢复。"""
import os


class RecycleBinView:
    """通过 Windows 外壳打开回收站，不做任何删除或恢复动作。"""

    TARGET = 'shell:RecycleBinFolder'

    def __init__(self, opener=None):
        self._opener = opener or os.startfile

    def open(self):
        self._opener(self.TARGET)
        return self.TARGET
