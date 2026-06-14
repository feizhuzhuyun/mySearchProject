"""
Excel 产品导入对话框 — 文件选择 → 列映射 → 预览 → 导入。
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import openpyxl

from database import Database


# ── 列名自动匹配关键字 ──
CODE_KEYWORDS = ["69码", "code", "条码", "barcode", "编码", "full_code", "ean"]
NAME_KEYWORDS = ["名称", "name", "品名", "产品名称", "产品", "product"]
DESC_KEYWORDS = ["描述", "desc", "description", "产品描述", "规格", "说明"]


def _auto_detect(headers: list[str]) -> dict[str, int]:
    """根据表头关键词自动匹配列索引。返回 {col_type: index}。"""

    result: dict[str, int] = {}
    for i, h in enumerate(headers):
        h_lower = str(h).strip().lower()
        if "code" not in result and any(k in h_lower for k in CODE_KEYWORDS):
            result["code"] = i
        elif "name" not in result and any(k in h_lower for k in NAME_KEYWORDS):
            result["name"] = i
        elif "desc" not in result and any(k in h_lower for k in DESC_KEYWORDS):
            result["desc"] = i

    # 未匹配时回退：第 0 列视为 code，第 1 列 name，第 2 列 desc
    if "code" not in result and len(headers) > 0:
        result["code"] = 0
    if "name" not in result and len(headers) > 1:
        result["name"] = 1
    if "desc" not in result and len(headers) > 2:
        result["desc"] = 2

    return result


# ---------------------------------------------------------------------------
# 导入对话框
# ---------------------------------------------------------------------------
class ImportDialog(QDialog):
    """Excel 产品数据导入对话框。"""

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self._db = database
        self._ws = None          # 当前工作表
        self._headers: list[str] = []
        self._data_rows: list[list] = []  # 数据行（不含表头）
        self._all_rows: list[list] = []   # 所有原始行

        self.setWindowTitle("导入产品数据")
        self.setMinimumSize(640, 480)
        self.resize(720, 540)
        self._setup_ui()

    # ── UI 构建 ──────────────────────────────────────────────────
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── 文件选择行 ──
        file_layout = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("选择 Excel 文件 (.xlsx / .xls) …")
        self.file_edit.setReadOnly(True)
        file_layout.addWidget(self.file_edit)

        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse_file)
        file_layout.addWidget(btn_browse)
        layout.addLayout(file_layout)

        # ── 列映射 ──
        form = QFormLayout()

        self.cb_code = QComboBox()
        self.cb_code.setEnabled(False)
        form.addRow("69 码列：", self.cb_code)

        self.cb_name = QComboBox()
        self.cb_name.setEnabled(False)
        form.addRow("产品名称列：", self.cb_name)

        self.cb_desc = QComboBox()
        self.cb_desc.setEnabled(False)
        form.addRow("产品描述列：", self.cb_desc)

        self.cb_has_header = QCheckBox("首行为表头")
        self.cb_has_header.setChecked(True)
        self.cb_has_header.stateChanged.connect(self._on_header_changed)
        form.addRow("", self.cb_has_header)

        layout.addLayout(form)

        # ── 预览表格 ──
        self.preview_label = QLabel("预览（前 10 行）：")
        layout.addWidget(self.preview_label)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # ── 按钮 ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("导入")
        buttons.accepted.connect(self._do_import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── 文件浏览 ─────────────────────────────────────────────────
    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择产品 Excel 文件",
            "",
            "Excel 文件 (*.xlsx *.xls);;所有文件 (*)",
        )
        if not path:
            return
        self.file_edit.setText(path)
        self._load_excel(path)

    def _load_excel(self, path: str):
        try:
            wb = openpyxl.load_workbook(path, read_only=True)
            self._ws = wb.active
        except Exception as exc:
            QMessageBox.warning(self, "打开失败", f"无法读取 Excel 文件：\n{exc}")
            return

        # 读取所有数据
        self._all_rows = []
        for row in self._ws.iter_rows(values_only=True):
            # 跳过全空行
            if all(v is None for v in row):
                continue
            self._all_rows.append([str(v) if v is not None else "" for v in row])

        if not self._all_rows:
            QMessageBox.warning(self, "无数据", "工作表为空。")
            return

        self._on_header_changed()
        self._rebuild_combo_boxes()

    # ── 列映射组合框 ─────────────────────────────────────────────
    def _rebuild_combo_boxes(self):
        headers = self._headers
        for cb in (self.cb_code, self.cb_name, self.cb_desc):
            cb.clear()
            cb.setEnabled(True)
            for h in headers:
                cb.addItem(h)

        # 自动匹配
        detected = _auto_detect(headers)
        if "code" in detected:
            self.cb_code.setCurrentIndex(detected["code"])
        if "name" in detected:
            self.cb_name.setCurrentIndex(detected["name"])
        if "desc" in detected:
            self.cb_desc.setCurrentIndex(detected["desc"])

        self._refresh_preview()

    def _on_header_changed(self):
        """切换"首行为表头"时重新确定表头与数据行。"""
        if not self._all_rows:
            return

        if self.cb_has_header.isChecked():
            self._headers = self._all_rows[0]
            self._data_rows = self._all_rows[1:]
        else:
            n_cols = max(len(r) for r in self._all_rows) if self._all_rows else 1
            self._headers = [f"列 {chr(65 + i)}" for i in range(n_cols)]
            self._data_rows = self._all_rows

        self._rebuild_combo_boxes()

    # ── 预览 ─────────────────────────────────────────────────────
    def _refresh_preview(self):
        if not self._headers:
            return

        rows = self._data_rows[:10]
        self.table.setColumnCount(len(self._headers))
        self.table.setHorizontalHeaderLabels(self._headers)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                if c < len(self._headers):
                    self.table.setItem(r, c, QTableWidgetItem(str(val)))

    # ── 执行导入 ─────────────────────────────────────────────────
    def _do_import(self):
        if not self._data_rows:
            QMessageBox.warning(self, "无数据", "没有可导入的数据行。")
            return

        ci = self.cb_code.currentIndex()
        ni = self.cb_name.currentIndex()
        di = self.cb_desc.currentIndex()
        if ci < 0 or ni < 0:
            QMessageBox.warning(self, "列映射", "请至少选择 69 码列和产品名称列。")
            return

        # 组装数据
        records = []
        for row in self._data_rows:
            code = str(row[ci]).strip() if ci < len(row) else ""
            name = str(row[ni]).strip() if ni < len(row) else ""
            desc = str(row[di]).strip() if di >= 0 and di < len(row) else ""
            if code and name:
                records.append((code, name, desc))

        if not records:
            QMessageBox.warning(self, "无数据", "过滤后无可导入的有效行（需要 69 码 + 名称）。")
            return

        try:
            n = self._db.import_products(records)
            QMessageBox.information(
                self, "导入完成",
                f"成功导入 {n} 条产品记录。\n"
                f"（跳过 {len(self._data_rows) - n} 条重复/无效行）"
            )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
