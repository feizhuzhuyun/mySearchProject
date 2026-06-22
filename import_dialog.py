"""
产品数据导入对话框 — CSV/Excel 文件选择 → 列映射 → 预览 → 导入。
v2.0: 支持完整 CSV 列映射 + 图片 URL 下载 + 规格入库。
"""
import csv, os, urllib.request, threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
import openpyxl
from database import Database


# ── 列名自动匹配关键字 ──
CODE_KEYWORDS = ["69码", "code", "条码", "barcode", "编码", "full_code", "ean", "sku(必填)", "sku"]
NAME_KEYWORDS = ["名称", "name", "品名", "产品名称", "product"]
DESC_KEYWORDS = ["描述", "desc", "description", "产品描述", "规格", "说明"]
IMAGE_URL_KEYWORDS = ["图片url", "image", "主图", "图片", "url", "img"]
SPEC_KEYWORD_MAP = {
    "商品净重（g）": "商品净重", "重量": "商品净重", "weight": "商品净重", "商品净重": "商品净重",
    "长(cm)": "长", "长": "长", "length": "长",
    "宽(cm)": "宽", "宽": "宽", "width": "宽",
    "高(cm)": "高", "高": "高", "height": "高",
    "英文报关": "英文报关", "english_declare": "英文报关",
    "中文报关": "中文报关", "chinese_declare": "中文报关",
    "海关编码": "海关编码", "hs_code": "海关编码", "hscode": "海关编码",
    "开发员": "开发员", "developer": "开发员",
}


def _auto_detect(headers: list[str]) -> dict[str, int]:
    """根据表头关键词自动匹配列索引。"""
    result: dict[str, int] = {}
    spec_candidates: dict[str, int] = {}

    for i, h in enumerate(headers):
        h_lower = str(h).strip().lower()
        if "code" not in result and any(k in h_lower for k in CODE_KEYWORDS):
            result["code"] = i
        elif "name" not in result and any(k in h_lower for k in NAME_KEYWORDS):
            result["name"] = i
        elif "desc" not in result and any(k in h_lower for k in DESC_KEYWORDS):
            result["desc"] = i
        elif "image_url" not in result and any(k in h_lower for k in IMAGE_URL_KEYWORDS):
            result["image_url"] = i
        else:
            # 尝试匹配规格列
            for kw, spec_name in SPEC_KEYWORD_MAP.items():
                if kw in h_lower:
                    spec_candidates[spec_name] = i
                    break

    # 合并规格列（去重 — 同一个 spec_name 只保留最先匹配到的列）
    seen_specs = set()
    for spec_name, idx in spec_candidates.items():
        if spec_name not in seen_specs:
            seen_specs.add(spec_name)
            result[f"spec:{spec_name}"] = idx

    # 回退
    if "code" not in result and len(headers) > 0:
        result["code"] = 0
    if "name" not in result and len(headers) > 1:
        result["name"] = 1

    return result


# ═══════════════════════════════════════════════════════════════════
# 后台图片下载线程
# ═══════════════════════════════════════════════════════════════════
class ImageDownloadWorker(QThread):
    """后台下载 CSV 中的产品图片到本地缓存。"""
    progress = Signal(int, int)   # current, total
    finished = Signal(int)        # success count

    def __init__(self, db: Database, cache_dir: str, downloads: list[tuple[int, str]]):
        """
        downloads: [(product_id, image_url), ...]
        """
        super().__init__()
        self._db = db
        self._cache_dir = cache_dir
        self._downloads = downloads

    def run(self):
        os.makedirs(self._cache_dir, exist_ok=True)
        success = 0
        total = len(self._downloads)
        for i, (pid, url) in enumerate(self._downloads):
            try:
                # 用 product_id 作为文件名
                ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
                if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                    ext = ".jpg"
                local = os.path.join(self._cache_dir, f"{pid}{ext}")
                if not os.path.exists(local):
                    urllib.request.urlretrieve(url, local)
                self._db.set_product_main_image_local(pid, local)
                success += 1
            except Exception:
                pass
            self.progress.emit(i + 1, total)
        self.finished.emit(success)


# ═══════════════════════════════════════════════════════════════════
# 导入对话框
# ═══════════════════════════════════════════════════════════════════
class ImportDialog(QDialog):
    """CSV/Excel 产品数据导入对话框。v2.0 支持完整列映射 + 图片下载。"""

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self._db = database
        self._ws = None
        self._headers: list[str] = []
        self._data_rows: list[list] = []
        self._all_rows: list[list] = []

        self.setWindowTitle("导入产品数据")
        self.setMinimumSize(720, 550)
        self.resize(780, 600)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── 文件选择行 ──
        file_layout = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("选择 CSV 或 Excel 文件…")
        self.file_edit.setReadOnly(True)
        file_layout.addWidget(self.file_edit)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse_file)
        file_layout.addWidget(btn_browse)
        layout.addLayout(file_layout)

        # ── 列映射 ──
        form = QFormLayout()
        self.cb_code = QComboBox(); self.cb_code.setEnabled(False)
        form.addRow("69码/SKU列：", self.cb_code)
        self.cb_name = QComboBox(); self.cb_name.setEnabled(False)
        form.addRow("产品名称列：", self.cb_name)
        self.cb_desc = QComboBox(); self.cb_desc.setEnabled(False)
        form.addRow("产品描述列：", self.cb_desc)
        self.cb_image = QComboBox(); self.cb_image.setEnabled(False)
        form.addRow("图片URL列：", self.cb_image)

        self.cb_has_header = QCheckBox("首行为表头")
        self.cb_has_header.setChecked(True)
        self.cb_has_header.stateChanged.connect(self._on_header_changed)
        form.addRow("", self.cb_has_header)

        self.spec_mapping_label = QLabel("")
        self.spec_mapping_label.setWordWrap(True)
        self.spec_mapping_label.setStyleSheet("color: #8b95a5; font-size: 11px;")
        form.addRow("自动识别的规格列：", self.spec_mapping_label)
        layout.addLayout(form)

        # ── 预览表格 ──
        self.preview_label = QLabel("预览（前 10 行）：")
        layout.addWidget(self.preview_label)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # ── 进度条 ──
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # ── 按钮 ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("导入")
        buttons.accepted.connect(self._do_import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._detected: dict[str, int] = {}

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择产品数据文件", "",
            "数据文件 (*.csv *.xlsx *.xls);;CSV (*.csv);;Excel (*.xlsx *.xls);;所有文件 (*)",
        )
        if not path:
            return
        self.file_edit.setText(path)
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".csv":
                self._load_csv(path)
            else:
                self._load_excel(path)
        except Exception as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    def _load_csv(self, path: str):
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            self._all_rows = [[c for c in row] for row in reader if any(v for v in row)]
        if not self._all_rows:
            QMessageBox.warning(self, "无数据", "CSV 文件为空。")
            return
        self._on_header_changed()
        self._rebuild_combo_boxes()

    def _load_excel(self, path: str):
        wb = openpyxl.load_workbook(path, read_only=True)
        self._ws = wb.active
        self._all_rows = []
        for row in self._ws.iter_rows(values_only=True):
            if all(v is None for v in row):
                continue
            self._all_rows.append([str(v) if v is not None else "" for v in row])
        if not self._all_rows:
            QMessageBox.warning(self, "无数据", "工作表为空。")
            return
        self._on_header_changed()
        self._rebuild_combo_boxes()

    def _rebuild_combo_boxes(self):
        headers = self._headers
        for cb in (self.cb_code, self.cb_name, self.cb_desc, self.cb_image):
            cb.clear()
            cb.setEnabled(True)
            for h in headers:
                cb.addItem(h)

        self._detected = _auto_detect(headers)
        if "code" in self._detected:
            self.cb_code.setCurrentIndex(self._detected["code"])
        if "name" in self._detected:
            self.cb_name.setCurrentIndex(self._detected["name"])
        if "desc" in self._detected:
            self.cb_desc.setCurrentIndex(self._detected["desc"])
        if "image_url" in self._detected:
            self.cb_image.setCurrentIndex(self._detected["image_url"])

        # 显示自动识别的规格列
        spec_lines = []
        for k, v in self._detected.items():
            if k.startswith("spec:"):
                spec_lines.append(f"{k[5:]} ← 列{v+1}")
        self.spec_mapping_label.setText("\n".join(spec_lines) if spec_lines else "（无）")

        self._refresh_preview()

    def _on_header_changed(self):
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

    def _do_import(self):
        if not self._data_rows:
            QMessageBox.warning(self, "无数据", "没有可导入的数据行。")
            return
        ci = self.cb_code.currentIndex()
        ni = self.cb_name.currentIndex()
        if ci < 0 or ni < 0:
            QMessageBox.warning(self, "列映射", "请至少选择 69 码列和产品名称列。")
            return
        di = self.cb_desc.currentIndex()
        ii = self.cb_image.currentIndex()

        # 组装数据
        records = []
        spec_records: dict[str, list[tuple]] = {}  # full_code → [(group, name, value), ...]
        image_downloads: list[tuple[str, str]] = []  # [(full_code, url), ...]

        for row in self._data_rows:
            code = str(row[ci]).strip() if ci < len(row) else ""
            name = str(row[ni]).strip() if ni < len(row) else ""
            if not code or not name:
                continue
            desc = str(row[di]).strip() if di >= 0 and di < len(row) else ""
            img_url = str(row[ii]).strip() if ii >= 0 and ii < len(row) else ""

            # 收集图片下载
            if img_url and img_url.startswith("http"):
                image_downloads.append((code, img_url))

            # 收集规格
            specs = []
            for k, idx in self._detected.items():
                if k.startswith("spec:") and idx < len(row):
                    val = str(row[idx]).strip()
                    if val and val != "0" and val != "0.0":
                        spec_name = k[5:]  # 去掉 "spec:" 前缀
                        group = _spec_group_for(spec_name)
                        specs.append((group, spec_name, val, "csv"))
            if specs:
                spec_records[code] = specs

            records.append((code, name, desc, img_url))

        if not records:
            QMessageBox.warning(self, "无数据", "过滤后无可导入的有效行。")
            return

        # 导入产品
        n = self._db.import_products(records)

        # 导入规格
        n_specs = 0
        for code, specs in spec_records.items():
            prod = self._db.get_product_by_code(code)
            if prod:
                n_specs += self._db.import_product_specs(prod["id"], specs)

        # 后台下载图片
        if image_downloads:
            cache_dir = os.path.join(os.path.dirname(self._db._db_path), "product_images")
            downloads = []
            for code, url in image_downloads:
                prod = self._db.get_product_by_code(code)
                if prod:
                    downloads.append((prod["id"], url))

            if downloads:
                self.progress.setVisible(True)
                self.progress.setMaximum(len(downloads))
                self._worker = ImageDownloadWorker(self._db, cache_dir, downloads)
                self._worker.progress.connect(lambda c, t: self.progress.setValue(c))
                self._worker.finished.connect(lambda s: self._on_download_done(s, n, n_specs))
                self._worker.start()
                # 禁用导入按钮防止重复点击
                self.findChild(QDialogButtonBox).button(
                    QDialogButtonBox.StandardButton.Ok
                ).setEnabled(False)
                return  # 等待下载完成

        self._show_result(n, n_specs, 0)

    def _on_download_done(self, img_ok: int, n_prod: int, n_specs: int):
        self._show_result(n_prod, n_specs, img_ok)

    def _show_result(self, n_prod: int, n_specs: int, n_img: int):
        msg = f"导入 {n_prod} 个产品"
        if n_specs:
            msg += f"\n规格数据：{n_specs} 条"
        if n_img:
            msg += f"\n下载主图：{n_img} 张"
        QMessageBox.information(self, "导入完成", msg)
        self.accept()


def _spec_group_for(spec_name: str) -> str:
    """根据规格名返回分组。"""
    physical = {"长", "宽", "高", "商品净重", "重量"}
    customs = {"英文报关", "中文报关", "海关编码"}
    if spec_name in physical:
        return "物理参数"
    if spec_name in customs:
        return "报关信息"
    return "基本规格"
