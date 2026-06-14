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
    "nas_root_paths": [],
    "last_scan_times": {},
    "db_path": os.path.join(_BASE_DIR, "data", "mysearch.db"),
}


class Config:
    """应用配置管理器（JSON 文件，原子写入，支持多 NAS 路径）。"""

    def __init__(self, path: str = CONFIG_PATH):
        self._path = path
        self._data: dict = {}
        self.load()
        self._migrate()

    # ── 读写 ─────────────────────────────────────────────────────
    def load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}
        for k, v in DEFAULT_CONFIG.items():
            if k not in self._data:
                self._data[k] = v

    def _migrate(self):
        """向后兼容：旧版 nas_root_path 字符串 → nas_root_paths 数组。"""
        old_path = self._data.pop("nas_root_path", None)
        old_time = self._data.pop("last_scan_time", None)
        if old_path and not self._data.get("nas_root_paths"):
            self._data["nas_root_paths"] = [old_path]
        if old_time and not self._data.get("last_scan_times"):
            self._data["nas_root_paths"] = self._data.get("nas_root_paths", [])
            times = {}
            for p in self._data["nas_root_paths"]:
                times[p] = old_time
            self._data["last_scan_times"] = times
        # 清理旧字段
        self._data.pop("nas_root_path", None)
        self._data.pop("last_scan_time", None)

    def save(self):
        """原子写入。"""
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp_path = self._path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    # ── 多路径属性 ───────────────────────────────────────────────
    @property
    def nas_root_paths(self) -> list[str]:
        return self._data.get("nas_root_paths", [])

    @nas_root_paths.setter
    def nas_root_paths(self, paths: list[str]):
        self._data["nas_root_paths"] = [p for p in paths if p.strip()]
        self.save()

    def add_nas_path(self, path: str):
        if path and path not in self._data.get("nas_root_paths", []):
            self._data.setdefault("nas_root_paths", []).append(path)
            self.save()

    def remove_nas_path(self, path: str):
        paths = self._data.get("nas_root_paths", [])
        if path in paths:
            paths.remove(path)
            times = self._data.get("last_scan_times", {})
            times.pop(path, None)
            self.save()

    def get_scan_time(self, path: str) -> float:
        return self._data.get("last_scan_times", {}).get(path, 0.0)

    def set_scan_time(self, path: str, t: float):
        self._data.setdefault("last_scan_times", {})[path] = t
        self.save()

    # ── 向后兼容（旧代码通过 nas_root_path 访问第一个路径） ─────────
    @property
    def nas_root_path(self) -> str:
        paths = self._data.get("nas_root_paths", [])
        return paths[0] if paths else ""

    @nas_root_path.setter
    def nas_root_path(self, value: str):
        if value:
            self._data["nas_root_paths"] = [value]
        else:
            self._data["nas_root_paths"] = []
        self.save()

    @property
    def last_scan_time(self) -> float:
        times = self._data.get("last_scan_times", {})
        return max(times.values()) if times else 0.0

    @last_scan_time.setter
    def last_scan_time(self, value: float):
        for p in self._data.get("nas_root_paths", []):
            self._data.setdefault("last_scan_times", {})[p] = value
        self.save()

    # ── 通用属性 ─────────────────────────────────────────────────
    @property
    def db_path(self) -> str:
        p = self._data.get("db_path", DEFAULT_CONFIG["db_path"])
        if not os.path.isabs(p):
            p = os.path.join(_BASE_DIR, p)
        return p

    @property
    def is_configured(self) -> bool:
        return bool(self._data.get("nas_root_paths", []))
