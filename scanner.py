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
    path_label = Signal(str)             # 当前扫描的路径标签
    status_message = Signal(str)         # 当前状态文字
    finished = Signal(dict)              # 扫描完成统计
    error = Signal(str)                  # 错误信息

    def __init__(
        self,
        database: Database,
        root_paths: list[str],
        incremental: bool = False,
        last_scan_times: dict | None = None,
    ):
        super().__init__()
        self._db = database
        self._root_paths = root_paths
        self._incremental = incremental
        self._last_scan_times = last_scan_times or {}

    @staticmethod
    def single_path(
        database: Database, root_path: str,
        incremental: bool = False, last_scan_time: float = 0.0,
    ) -> "ScanWorker":
        """向后兼容：单路径构造器。"""
        times = {root_path: last_scan_time} if root_path else {}
        return ScanWorker(database, [root_path], incremental, times)

    def run(self):
        try:
            stats = self._scan_all()
            self.finished.emit(stats)
        except Exception as exc:
            self.error.emit(str(exc))

    # ── 多路径扫描 ───────────────────────────────────────────────
    def _scan_all(self) -> dict:
        total_stats = {"files": 0, "folders": 0, "codes": 0, "linked": 0}
        for i, root_path in enumerate(self._root_paths):
            label = f"[{i+1}/{len(self._root_paths)}] {os.path.basename(root_path) or root_path}"
            self.path_label.emit(label)
            stats = self._scan_one(root_path)
            for k in total_stats:
                total_stats[k] += stats.get(k, 0)
        return total_stats

    def _scan_one(self, root_path: str) -> dict:
        root = Path(root_path)
        if not root.exists():
            self.status_message.emit(f"目录不存在，跳过: {root_path}")
            return {"files": 0, "folders": 0, "codes": 0, "linked": 0}

        last_scan = self._last_scan_times.get(root_path, 0.0) if self._incremental else 0.0
        self.status_message.emit("正在遍历目录…")

        # Step 1: 收集图片文件
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

                if self._incremental and mtime <= last_scan:
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

        image_rows = []
        folder_set: set[str] = set()
        for i, f in enumerate(all_files):
            image_rows.append((
                f["full_path"], f["folder_path"], f["folder_name"],
                f["file_name"], int(f["last_modified"]),
            ))
            folder_set.add(f["folder_path"])
            if i % 200 == 0:
                self.progress.emit(i, total)
        self.progress.emit(total, total)

        self._db.import_images(image_rows)

        self.status_message.emit("正在提取文件夹码…")
        code_rows = []
        for folder_path in folder_set:
            codes = CODE_RE.findall(os.path.basename(folder_path))
            for c in codes:
                code_rows.append((folder_path, c))
        if code_rows:
            self._db.import_folder_codes(code_rows)

        self.status_message.emit("正在匹配产品…")
        self._db.rebuild_links()

        stats = {
            "files": len(image_rows),
            "folders": len(folder_set),
            "codes": len(code_rows),
            "linked": self._db.get_link_count(),
        }
        n = os.path.basename(root_path)
        self.status_message.emit(
            f"{n} — {stats['files']} 张图片, {stats['folders']} 个文件夹"
        )
        return stats


class ScanThread(QThread):
    """专用扫描线程 — 重写 run() 直接调用 worker，避免 started 信号时序问题。"""

    def __init__(self, worker: ScanWorker, parent=None):
        super().__init__(parent)
        self._worker = worker

    def run(self):
        self._worker.run()
