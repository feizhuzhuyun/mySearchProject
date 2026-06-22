"""
知识库管理标签页 — 产品级数据来源追踪，精炼布局。
"""
import os
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QTextEdit,
)
from database import Database
from config import Config
from build_knowledge_base import build_prompt, scan_structure
from widgets import Card


class KnowledgeTab(QWidget):
    """🧠 知识库 — 产品数据来源追踪 + 导入/导出/提示词。"""

    status_changed = Signal()

    def __init__(self, database: Database, config: Config, parent=None):
        super().__init__(parent)
        self._db = database
        self._cfg = config
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ── 标题行 ──
        header = QHBoxLayout()
        title = QLabel("🧠 知识库")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.clicked.connect(self.refresh_status)
        header.addWidget(self.btn_refresh)
        layout.addLayout(header)

        # ── 数据总览（一行） ──
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "background:#1e2a38; border-radius:6px; padding:10px 14px; "
            "color:#cdd6f4; font-size:12px;"
        )
        layout.addWidget(self.summary_label)

        # ── 产品数据来源明细表 ──
        self.table = QTableWidget()
        self.table.setObjectName("kbTable")
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "产品码", "产品名称", "CSV", "知识库", "图片", "完整度"
        ])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 80)
        self.table.setMinimumHeight(200)
        layout.addWidget(self.table, 1)

        # ── 操作区（紧凑行） ──
        actions = QHBoxLayout()
        actions.setSpacing(6)

        btn_import = QPushButton("📥 导入 JSONL")
        btn_import.setToolTip("导入 LLM 生成的知识库文件")
        btn_import.setFixedHeight(28)
        btn_import.clicked.connect(self._on_import)
        actions.addWidget(btn_import)

        btn_export = QPushButton("📤 导出 JSONL")
        btn_export.setToolTip("导出当前所有产品为 JSONL")
        btn_export.setFixedHeight(28)
        btn_export.clicked.connect(self._on_export)
        actions.addWidget(btn_export)

        actions.addSpacing(12)

        btn_prompt = QPushButton("📋 复制 LLM 提示词")
        btn_prompt.setToolTip("一键复制完整提示词给 AI")
        btn_prompt.setFixedHeight(28)
        btn_prompt.setStyleSheet(
            "QPushButton { background-color: #2a4a6b; font-weight: bold; }"
            "QPushButton:hover { background-color: #3a5a7b; }"
        )
        btn_prompt.clicked.connect(self._on_copy_prompt)
        actions.addWidget(btn_prompt)

        actions.addStretch()

        btn_clear_csv = QPushButton("清CSV")
        btn_clear_csv.setToolTip("只清除 CSV 导入的产品")
        btn_clear_csv.setFixedHeight(26)
        btn_clear_csv.clicked.connect(lambda: self._on_clear("csv"))
        actions.addWidget(btn_clear_csv)

        btn_clear_llm = QPushButton("清知识库")
        btn_clear_llm.setToolTip("只清除知识库导入的产品")
        btn_clear_llm.setFixedHeight(26)
        btn_clear_llm.clicked.connect(lambda: self._on_clear("llm"))
        actions.addWidget(btn_clear_llm)

        btn_clear_scan = QPushButton("清扫描")
        btn_clear_scan.setToolTip("只清除扫描索引")
        btn_clear_scan.setFixedHeight(26)
        btn_clear_scan.clicked.connect(self._on_clear_scan)
        actions.addWidget(btn_clear_scan)

        layout.addLayout(actions)

        # 首次加载
        self.refresh_status()

    # ── 刷新 ──────────────────────────────────────────────────────
    def refresh_status(self):
        matrix = self._db.get_product_source_matrix()
        self._populate_summary(matrix)
        self._populate_table(matrix)

    def _populate_summary(self, matrix: list[dict]):
        total = len(matrix)
        csv_n = sum(1 for m in matrix if m["csv_specs"] + m["auto_specs"] > 0)
        kb_n = sum(1 for m in matrix if m["llm_specs"] > 0)
        has_img = sum(1 for m in matrix if m["image_count"] > 0)
        total_img = sum(m["image_count"] for m in matrix)
        total_csv = sum(m["csv_specs"] + m["auto_specs"] for m in matrix)
        total_llm = sum(m["llm_specs"] for m in matrix)

        lines = [
            f"📦 {total} 个产品",
            f"📥 CSV/自动: {csv_n} 个（{total_csv} 条）",
            f"🧠 知识库: {kb_n} 个（{total_llm} 条）",
            f"📷 扫描: {has_img} 个有图（{total_img} 张）",
        ]
        self.summary_label.setText("  │  ".join(lines))

    def _populate_table(self, matrix: list[dict]):
        self.table.setRowCount(len(matrix))
        for i, m in enumerate(matrix):
            # 产品码
            code_item = QTableWidgetItem(m["full_code"])
            code_item.setToolTip(m["full_code"])
            self.table.setItem(i, 0, code_item)

            # 名称
            name_item = QTableWidgetItem(m["name"][:50])
            name_item.setToolTip(m["name"])
            self.table.setItem(i, 1, name_item)

            # CSV + auto 规格数
            csv_total = m["csv_specs"] + m["auto_specs"]
            csv_item = QTableWidgetItem(str(csv_total) if csv_total > 0 else "—")
            csv_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 2, csv_item)

            # 知识库规格数
            llm_item = QTableWidgetItem(
                str(m["llm_specs"]) if m["llm_specs"] > 0 else "—"
            )
            llm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 3, llm_item)

            # 图片数
            img_item = QTableWidgetItem(
                str(m["image_count"]) if m["image_count"] > 0 else "—"
            )
            img_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 4, img_item)

            # 完整度
            score = 0
            if csv_total > 0:
                score += 1
            if m["llm_specs"] > 0:
                score += 1
            if m["image_count"] > 0:
                score += 1
            labels = {0: "○", 1: "◐", 2: "◑", 3: "●"}
            comp_item = QTableWidgetItem(labels[score])
            comp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            comp_item.setToolTip({0: "无数据", 1: "单一来源", 2: "两个来源", 3: "三源完整"}[score])
            self.table.setItem(i, 5, comp_item)

            # 行高
            self.table.setRowHeight(i, 28)

    # ── 操作 ──────────────────────────────────────────────────────
    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择知识库文件", "", "JSONL 文件 (*.jsonl);;所有文件 (*)",
        )
        if not path:
            return
        try:
            stats = self._db.import_jsonl(path)
            QMessageBox.information(
                self, "导入完成",
                f"产品：{stats['products']} 个\n规格：{stats['specs']} 条\n"
                + (f"跳过：{len(stats['errors'])} 行" if stats.get("errors") else "")
            )
            self.refresh_status()
            self.status_changed.emit()
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出知识库", "products.jsonl", "JSONL 文件 (*.jsonl)",
        )
        if not path:
            return
        try:
            n = self._db.export_jsonl(path)
            QMessageBox.information(self, "导出完成", f"导出 {n} 个产品组到\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _on_copy_prompt(self):
        root = self._cfg.nas_root_path
        if not root or not os.path.isdir(root):
            QMessageBox.warning(self, "提示", "请先在设置中配置 NAS 图片根目录")
            return
        structure = scan_structure(root)
        prompt = build_prompt(root, structure)
        QApplication.clipboard().setText(prompt)
        QMessageBox.information(
            self, "已复制",
            f"提示词已复制到剪贴板（{len(prompt)} 字符）。\n可直接粘贴给 LLM。"
        )

    def _on_clear(self, source: str):
        name = {"csv": "CSV 导入", "llm": "知识库"}.get(source, source)
        reply = QMessageBox.question(
            self, f"确认清除 {name} 数据",
            f"将删除所有来源为「{name}」的产品和规格。\n"
            f"其他数据不受影响。\n\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        stats = self._db.clear_source_data(source)
        QMessageBox.information(
            self, "清除完成",
            f"已删除 {stats['products']} 个产品\n{stats['specs']} 条规格",
        )
        self.refresh_status()
        self.status_changed.emit()

    def _on_clear_scan(self):
        reply = QMessageBox.question(
            self, "确认清除扫描索引",
            "将清空图片索引、文件夹码和产品关联。\n产品数据不受影响。\n\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._db.clear_index()
        self.refresh_status()
        self.status_changed.emit()
