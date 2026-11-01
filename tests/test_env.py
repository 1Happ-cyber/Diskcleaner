import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from diskcleaner import diagnostics
from diskcleaner.gui import pick_data_dir
from diskcleaner.shell import RecycleBinView


class ShellTests(unittest.TestCase):
    def test_recycle_bin_uses_shell_target(self):
        opened = []
        view = RecycleBinView(opener=opened.append)
        self.assertEqual(view.open(), 'shell:RecycleBinFolder')
        self.assertEqual(opened, ['shell:RecycleBinFolder'])

    def test_recycle_bin_propagates_failure(self):
        def broken(target):
            raise OSError('shell 不可用')

        with self.assertRaises(OSError):
            RecycleBinView(opener=broken).open()


class DiagnosticsTests(unittest.TestCase):
    def test_summary_reports_python_version(self):
        lines = diagnostics.summary()
        self.assertTrue(any('Python' in line for line in lines))
        self.assertTrue(any('依赖检查' in line for line in lines))

    def test_missing_dependencies_is_list(self):
        missing = diagnostics.missing_dependencies()
        self.assertIsInstance(missing, list)

    def test_environment_keys(self):
        info = diagnostics.environment()
        self.assertEqual(set(info), {'python', 'platform', 'tk'})


class DataDirTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_prefers_writable_directory(self):
        preferred = self.root / 'CourseDiskCleaner'
        picked, fallback = pick_data_dir(preferred)
        self.assertEqual(picked, preferred)
        self.assertFalse(fallback)
        self.assertTrue(preferred.is_dir())

    def test_falls_back_when_preferred_is_a_file(self):
        blocked = self.root / 'blocked'
        blocked.write_text('not a directory', encoding='utf-8')
        with patch.object(Path, 'cwd', return_value=self.root):
            picked, fallback = pick_data_dir(blocked)
        self.assertTrue(fallback)
        self.assertEqual(picked, self.root / 'DiskCleanerData')
        self.assertTrue(picked.is_dir())


if __name__ == '__main__':
    unittest.main()
