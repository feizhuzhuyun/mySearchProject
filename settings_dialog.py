"""设置对话框。"""
import os
from PySide6.QtWidgets import (QDialog,QDialogButtonBox,QFileDialog,QFrame,QHBoxLayout,QLabel,QLineEdit,QPushButton,QVBoxLayout)
from database import Database
from config import Config

class SettingsDialog(QDialog):
    """NAS 路径 + 数据库统计 — 配置入口。"""

    def __init__(self, database: Database, config: Config, parent=None):
        super().__init__(parent)
        self._db = database
        self._cfg = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── NAS 路径 ──
        nas_label = QLabel("NAS 图片根目录")
        nas_label.setStyleSheet("font-weight: 600; color: inherit;")
        layout.addWidget(nas_label)

        nas_row = QHBoxLayout()
        self.nas_edit = QLineEdit()
        self.nas_edit.setPlaceholderText("例如：Z:\\或 \\\\192.168.1.100\\images")
        nas_row.addWidget(self.nas_edit)

        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse_nas)
        nas_row.addWidget(btn_browse)
        layout.addLayout(nas_row)

        # ── 数据库路径（只读） ──
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
        self.nas_edit.setText(self._cfg.nas_root_path)
        self.db_path_label.setText(self._cfg.db_path)
        self._refresh_stats()

    def _refresh_stats(self):
        images = self._db.get_image_count()
        folders = self._db.get_folder_count()
        products = self._db.get_product_count()
        links = self._db.get_link_count()
        self.stats_label.setText(
            f"产品：{products} 条\n"
            f"图片：{images} 张    文件夹：{folders} 个    关联：{links} 组"
        )

    def _browse_nas(self):
        path = QFileDialog.getExistingDirectory(self, "选择 NAS 图片根目录", "")
        if path:
            self.nas_edit.setText(path)

    def _save(self):
        new_path = self.nas_edit.text().strip()
        self._cfg.nas_root_path = new_path
        self.accept()

