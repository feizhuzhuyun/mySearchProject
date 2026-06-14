"""
运行时配置 — 单例，从 config.json 读写。
"""

import json
import os
import tempfile
from pathlib import Path

# 基于脚本所在目录的绝对路径，避免从不同 CWD 启动时找不到配置
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "nas_root_path": "",
    "last_scan_time": 0,
    "db_path": os.path.join(_BASE_DIR, "data", "mysearch.db"),
}


class Config:
    """应用配置管理器（JSON 文件，原子写入）。"""

    def __init__(self, path: str = CONFIG_PATH):
        self._path = path
        self._data: dict = {}
        self.load()

    # ── 读写 ─────────────────────────────────────────────────────
    def load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}
        # 补全缺失的默认值
        for k, v in DEFAULT_CONFIG.items():
            if k not in self._data:
                self._data[k] = v

    def save(self):
        """原子写入：先写临时文件，再重命名，防止写一半崩溃导致配置损坏。"""
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp_path = self._path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._path)  # Windows 上也原子
        except Exception:
            # 写入失败时清理临时文件
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    # ── 便捷属性 ─────────────────────────────────────────────────
    @property
    def nas_root_path(self) -> str:
        return self._data.get("nas_root_path", "")

    @nas_root_path.setter
    def nas_root_path(self, value: str):
        self._data["nas_root_path"] = value
        self.save()

    @property
    def last_scan_time(self) -> float:
        return self._data.get("last_scan_time", 0.0)

    @last_scan_time.setter
    def last_scan_time(self, value: float):
        self._data["last_scan_time"] = value
        self.save()

    @property
    def db_path(self) -> str:
        p = self._data.get("db_path", DEFAULT_CONFIG["db_path"])
        if not os.path.isabs(p):
            p = os.path.join(_BASE_DIR, p)
        return p

    @property
    def is_configured(self) -> bool:
        return bool(self._data.get("nas_root_path", ""))
