"""
文件扫描器 — 遍历 NAS / 本地目录，收集图片元数据与文件夹码。

使用方式:
    worker = ScanWorker(database, root_path)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()
"""

import os
import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from database import Database


# 支持的图片扩展名
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# 文件夹名中提取四位连续数字的正则（69 码后四位）
# 提取文件夹名中所有四位连续数字（69码后四位）。
# 不能用 \b（Python 3 中 \w 包含中文，边界检测失效），用负向断言代替。
CODE_RE = re.compile(r"(?<!\d)\d{4}(?!\d)")


# ---------------------------------------------------------------------------
# 扫描工作线程
# ---------------------------------------------------------------------------
class ScanWorker(QObject):
    """在后台线程中执行扫描，通过信号报告进度与结果。"""

    # 信号
    progress = Signal(int, int)          # (current, total) — 文件级进度
    status_message = Signal(str)         # 当前状态文字
    finished = Signal(dict)              # 扫描完成统计
    error = Signal(str)                  # 错误信息

    def __init__(
        self,
        database: Database,
        root_path: str,
        incremental: bool = False,
        last_scan_time: float = 0.0,
    ):
        super().__init__()
        self._db = database
        self._root_path = root_path
        self._incremental = incremental
        self._last_scan_time = last_scan_time

    def run(self):
        """扫描入口（在 QThread 中执行）。"""
        try:
            stats = self._scan()
            self.finished.emit(stats)
        except Exception as exc:
            self.error.emit(str(exc))

    # ── 主扫描逻辑 ───────────────────────────────────────────────
    def _scan(self) -> dict:
        root = Path(self._root_path)
        if not root.exists():
            raise FileNotFoundError(f"目录不存在: {self._root_path}")

        self.status_message.emit("正在遍历目录…")

        # Step 1: 收集所有图片文件
        all_files: list[dict] = []
        for dirpath, dirnames, filenames in os.walk(root):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in IMAGE_EXTENSIONS:
                    continue
                full_path = os.path.join(dirpath, fname)
                rel_dir = os.path.relpath(dirpath, root)
                folder_name = os.path.basename(dirpath)

                try:
                    stat = os.stat(full_path)
                    mtime = stat.st_mtime
                except OSError:
                    continue

                # 增量模式：跳过未修改的文件
                if self._incremental and mtime <= self._last_scan_time:
                    continue

                all_files.append({
                    "full_path": full_path,
                    "folder_path": rel_dir,
                    "folder_name": folder_name,
                    "file_name": fname,
                    "last_modified": mtime,
                })

        total = len(all_files)
        if total == 0:
            self.status_message.emit("没有发现新图片。")
            return {"files": 0, "folders": 0, "codes": 0, "linked": 0}

        self.status_message.emit(f"发现 {total} 张图片，正在写入索引…")

        # Step 2: 批量写入 images 表
        image_rows = []
        folder_set: set[str] = set()
        for i, f in enumerate(all_files):
            image_rows.append((
                f["full_path"],
                f["folder_path"],
                f["folder_name"],
                f["file_name"],
                int(f["last_modified"]),
            ))
            folder_set.add(f["folder_path"])
            if i % 200 == 0:
                self.progress.emit(i, total)

        self.progress.emit(total, total)

        n_images = self._db.import_images(image_rows)

        # Step 3: 提取文件夹码
        # 从文件夹路径的每一层提取 4 位数字（69码后四位通常在父文件夹名中）
        self.status_message.emit("正在提取文件夹码…")
        code_rows = []
        seen = set()  # 去重 (folder_path, code)
        for folder_path in folder_set:
            parts = folder_path.replace("\\", "/").split("/")
            for part in parts:
                codes = CODE_RE.findall(part)
                for c in codes:
                    key = (folder_path, c)
                    if key not in seen:
                        seen.add(key)
                        code_rows.append((folder_path, c))

        n_codes = 0
        if code_rows:
            n_codes = self._db.import_folder_codes(code_rows)

        # Step 4: 重建产品-文件夹关联
        self.status_message.emit("正在匹配产品…")
        self._db.rebuild_links()
        n_linked = self._db.get_link_count()

        stats = {
            "files": n_images,
            "folders": len(folder_set),
            "codes": n_codes,
            "linked": n_linked,
        }
        self.status_message.emit(
            f"完成 — {n_images} 张图片, {len(folder_set)} 个文件夹, "
            f"{n_linked} 个关联产品"
        )
        return stats


class ScanThread(QThread):
    """专用扫描线程 — 重写 run() 直接调用 worker，避免 started 信号时序问题。"""

    def __init__(self, worker: ScanWorker, parent=None):
        super().__init__(parent)
        self._worker = worker

    def run(self):
        self._worker.run()
