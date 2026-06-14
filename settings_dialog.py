"""设置对话框 — 多NAS路径管理 + 数据库统计。"""
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout,
)
from database import Database
from config import Config


class SettingsDialog(QDialog):

    def __init__(self, database: Database, config: Config, parent=None):
        super().__init__(parent)
        self._db = database
        self._cfg = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(500)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── NAS 路径列表 ──
        nas_label = QLabel("NAS 图片根目录（可添加多个）")
        nas_label.setStyleSheet("font-weight: 600; color: inherit;")
        layout.addWidget(nas_label)

        self.path_list = QListWidget()
        self.path_list.setMaximumHeight(120)
        layout.addWidget(self.path_list)

        path_btn_row = QHBoxLayout()
        btn_add = QPushButton("＋ 添加")
        btn_add.clicked.connect(self._add_path)
        path_btn_row.addWidget(btn_add)
        btn_remove = QPushButton("－ 移除")
        btn_remove.clicked.connect(self._remove_path)
        path_btn_row.addWidget(btn_remove)
        path_btn_row.addStretch()
        layout.addLayout(path_btn_row)

        # ── 数据库路径 ──
        db_label = QLabel("数据库")
        db_label.setStyleSheet("font-weight: 600; color: inherit;")
        layout.addWidget(db_label)
        self.db_path_label = QLabel()
        self.db_path_label.setObjectName("settingsDbPath")
        layout.addWidget(self.db_path_label)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("settingsSep")
        layout.addWidget(sep)

        # ── 统计 ──
        stats_label = QLabel("统计")
        stats_label.setStyleSheet("font-weight: 600; color: inherit;")
        layout.addWidget(stats_label)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("settingsStats")
        layout.addWidget(self.stats_label)

        # ── 按钮 ──
        layout.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self):
        self.path_list.clear()
        for p in self._cfg.nas_root_paths:
            item = QListWidgetItem(p)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.path_list.addItem(item)
        self.db_path_label.setText(self._cfg.db_path)
        self._refresh_stats()

    def _add_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择 NAS 图片根目录", "")
        if path and path not in self._current_paths():
            item = QListWidgetItem(path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.path_list.addItem(item)

    def _remove_path(self):
        for item in self.path_list.selectedItems():
            self.path_list.takeItem(self.path_list.row(item))

    def _current_paths(self) -> list[str]:
        paths = []
        for i in range(self.path_list.count()):
            t = self.path_list.item(i).text().strip()
            if t:
                paths.append(t)
        return paths

    def _refresh_stats(self):
        images = self._db.get_image_count()
        folders = self._db.get_folder_count()
        products = self._db.get_product_count()
        links = self._db.get_link_count()
        self.stats_label.setText(
            f"产品：{products} 条\n"
            f"图片：{images} 张    文件夹：{folders} 个    关联：{links} 组"
        )

    def _save(self):
        self._cfg.nas_root_paths = self._current_paths()
        self.accept()

