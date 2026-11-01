"""生成独立演示目录，不覆盖已有文件。"""
from pathlib import Path
import tempfile

root = Path(tempfile.mkdtemp(prefix='disk-cleaner-demo-'))
(root / 'documents').mkdir()
(root / 'images').mkdir()
(root / 'documents' / 'notes.txt').write_bytes(b'course-demo\n' * 100)
(root / 'documents' / 'notes-copy.txt').write_bytes(b'course-demo\n' * 100)
(root / 'images' / 'sample.bin').write_bytes(bytes(range(256)) * 4096)
(root / 'empty.txt').write_bytes(b'')
(root / 'empty-copy.txt').write_bytes(b'')
print('Demo directory:', root)
print('Expected: 5 files, 1050976 bytes, 2 duplicate groups.')
print('No permission-restricted directory is created; see docs testing checklist.')
