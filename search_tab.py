"""检索标签页。"""
import os, time
from PySide6.QtCore import Qt, QPoint, QSize, QThread, QTimer, Signal
from PySide6.QtGui import QIcon,QImageReader,QPixmap,QPainter,QColor,QFont,QPen,QBrush
from PySide6.QtWidgets import (QApplication,QDialog,QFileDialog,QGridLayout,QHBoxLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QMessageBox,QPushButton,QScrollArea,QToolTip,QVBoxLayout,QWidget,QSplitter)
from config import Config
from database import Database
from import_dialog import ImportDialog
from scanner import ScanWorker, ScanThread
from widgets import Card, Placeholder
from settings_dialog import SettingsDialog

try:
    from models import get_instance as _get_model_instance
except ImportError:
    _get_model_instance = None

class SearchTab(QWidget):
    """📦 图片检索 — 搜索框 + 左侧文件夹列表 + 右侧图片网格。"""

    # 对外信号：状态变更（用于主窗口状态栏更新）
    status_changed = Signal()

    def __init__(self, database: Database, config: Config, parent=None):
        super().__init__(parent)
        self._db = database
        self._cfg = config
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 搜索栏容器 ──
        search_container = QWidget()
        search_container.setObjectName("searchContainer")
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(14, 10, 14, 10)

        # 搜索图标
        search_icon = QLabel("🔎")
        search_icon.setFixedWidth(22)
        search_icon.setStyleSheet("font-size: 15px;")
        search_layout.addWidget(search_icon)

        # 搜索输入
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("输入 69 码、关键字，或拖入图片搜索…")
        self.search_input.setFixedHeight(38)
        self.search_input.setAcceptDrops(True)
        search_layout.addWidget(self.search_input)
        layout.addWidget(search_container)

        # ── 菜单按钮栏 ──
        toolbar = QWidget()
        toolbar.setObjectName("searchToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(14, 6, 14, 6)
        toolbar_layout.setSpacing(6)

        self.btn_import = QPushButton("📥 导入产品")
        self.btn_import.setToolTip("从 Excel 导入产品数据")
        self.btn_import.setProperty("toolbarButton", "yes")
        self.btn_import.clicked.connect(self._on_import_products)
        toolbar_layout.addWidget(self.btn_import)

        self.btn_inc_scan = QPushButton("🔄 增量扫描")
        self.btn_inc_scan.setToolTip("扫描新增图片")
        self.btn_inc_scan.setProperty("toolbarButton", "yes")
        self.btn_inc_scan.clicked.connect(self._on_incremental_scan)
        toolbar_layout.addWidget(self.btn_inc_scan)

        self.btn_full_scan = QPushButton("🔁 重建索引")
        self.btn_full_scan.setToolTip("全量重建所有索引")
        self.btn_full_scan.setProperty("toolbarButton", "yes")
        self.btn_full_scan.clicked.connect(self._on_full_scan)
        toolbar_layout.addWidget(self.btn_full_scan)

        toolbar_layout.addStretch()

        # 状态指示器
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("searchStatusLabel")
        toolbar_layout.addWidget(self.status_label)

        # 设置按钮
        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setToolTip("设置 NAS 路径与查看统计")
        self.btn_settings.setProperty("toolbarButton", "yes")
        self.btn_settings.clicked.connect(self._on_open_settings)
        toolbar_layout.addWidget(self.btn_settings)

        layout.addWidget(toolbar)

        # ── 文件夹路径条（点击复制） ──
        self.path_bar = QLabel("请选择左侧结果")
        self.path_bar.setObjectName("pathBar")
        self.path_bar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.path_bar.setToolTip("点击复制路径")
        self.path_bar.setMinimumHeight(26)
        self.path_bar.setWordWrap(False)
        self.path_bar.mousePressEvent = self._on_path_bar_click
        layout.addWidget(self.path_bar)

        # ── 结果区域 — 左右分割 ──
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("searchSplitter")
        self.splitter.setHandleWidth(0)  # 固定不可拖拽

        # ── 左侧面板 — 搜索结果列表 ──
        left_card = Card(padding=6)
        self.result_list = QListWidget()
        self.result_list.setObjectName("searchResultList")
        self.result_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.result_list.setWordWrap(True)
        left_card.content.addWidget(self.result_list)

        # 复制全部69码按钮
        self.btn_copy_codes = QPushButton("📋 复制全部69码")
        self.btn_copy_codes.setToolTip("复制当前列表所有69码（换行分隔）")
        self.btn_copy_codes.setProperty("toolbarButton", "yes")
        self.btn_copy_codes.clicked.connect(self._on_copy_all_codes)
        self.btn_copy_codes.setVisible(False)
        left_card.content.addWidget(self.btn_copy_codes)

        self.splitter.addWidget(left_card)

        # ── 右侧面板 — 图片缩略图网格 ──
        right_card = Card(padding=6)
        self.thumb_scroll = QScrollArea()
        self.thumb_scroll.setObjectName("thumbScroll")
        self.thumb_scroll.setWidgetResizable(True)
        self.thumb_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.thumb_container = QWidget()
        self.thumb_grid = QGridLayout(self.thumb_container)
        self.thumb_grid.setContentsMargins(4, 4, 4, 4)
        self.thumb_grid.setSpacing(6)
        self.thumb_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.thumb_scroll.setWidget(self.thumb_container)
        right_card.content.addWidget(self.thumb_scroll)
        self.splitter.addWidget(right_card)

        self.splitter.setSizes([290, 210])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)  # 右侧固定 210px
        layout.addWidget(self.splitter, 1)

        # 缩略图缓存
        self._thumb_cache: dict[str, list[QPixmap]] = {}  # folder_path → pixmaps
        self._search_results: list[dict] = []
        self._all_codes: list[str] = []

        # 搜索输入 — 400ms 防抖自动搜索 + 回车立即搜索
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(400)
        self._search_timer.timeout.connect(self._on_search)
        self.search_input.textChanged.connect(self._on_input_changed)
        self.search_input.returnPressed.connect(self._on_search)

    # 当前高亮的行容器引用（用于取消旧选中）
    _selected_row: "QWidget | None" = None
    _SELECTION_STYLE = "background-color: #F0FFF0; border-radius: 4px;"

    def _highlight_row(self, item: QListWidgetItem):
        """给 item 的行容器设置稳定选中底色，同时清除旧选中。"""
        if self._selected_row is not None:
            try:
                self._selected_row.setStyleSheet("")
            except RuntimeError:
                pass
            self._selected_row = None

        row = self.result_list.itemWidget(item)
        if row is not None:
            row.setStyleSheet(self._SELECTION_STYLE)
            self._selected_row = row

    def _auto_select_first(self):
        """搜索完成后自动选中第一个结果 + 加载缩略图。"""
        if self.result_list.count() == 0:
            self._show_placeholder_right()
            return
        first = self.result_list.item(0)
        folder_path = first.data(Qt.ItemDataRole.UserRole)
        if not folder_path:
            self._show_placeholder_right()
            return

        self.result_list.setCurrentItem(first)
        self.result_list.scrollToTop()
        self._highlight_row(first)

        full = self._resolve_path(folder_path)
        self.path_bar.setText(full or folder_path)
        self._load_thumbnails(folder_path)

    # ── 搜索分发 ──────────────────────────────────────────────────
    def _on_input_changed(self, _text: str):
        """每次击键重置计时器，停止输入 400ms 后自动搜索。"""
        self._search_timer.start()

    def _on_search(self):
        query = self.search_input.text().strip()
        self._search_timer.stop()
        if not query:
            self.result_list.clear()
            self._show_placeholder_right()
            self.path_bar.setText("请选择左侧结果")
            return

        # 通过模型插件体系解析查询意图
        analyzer = _get_model_instance("query_analyzers", "LocalQueryAnalyzer") if _get_model_instance else None
        if analyzer is not None:
            intent = analyzer.analyze(query)
        else:
            # 降级：插件不可用时直接判断
            if query.isdigit():
                intent = type("Intent", (), {"mode": "code", "include_terms": [query]})()
            else:
                intent = type("Intent", (), {"mode": "keyword", "include_terms": [query]})()

        if intent.mode == "code":
            self._do_code_search(query)
        else:
            self._do_keyword_search(query)

    def _do_code_search(self, query: str):
        """69码渐进匹配。"""
        results = self._db.search_folders_by_code_tail(query)
        self._search_results = results
        self._populate_list(results)
        self._auto_select_first()
        n = len(query)
        if n < 4:
            hint = f"（输入 {4-n} 位以精确匹配）"
        elif n == 4:
            hint = "（精确后四位匹配）"
        else:
            hint = f"（已输入 {n} 位，逐步收敛中）"
        self.status_label.setText(
            f"69码 \"{query}\" — {len(results)} 个结果 {hint}"
        )

    def _do_keyword_search(self, query: str):
        """关键字搜索：匹配文件夹名。"""
        results = self._db.search_folders_by_keyword(query)
        self._search_results = results
        self._populate_list(results)
        self._auto_select_first()
        self.status_label.setText(
            f"关键字搜索 \"{query}\" — {len(results)} 个结果"
        )

    # ── 列表项格式化（可扩展接口） ──────────────────────────────────
    # 后续阶段可接入 AI 对 name / description 做简化处理。
    # 只需修改这两个方法的返回值，不影响 UI 框架。

    @staticmethod
    def _fmt_folder_label(folder_name: str) -> str:
        """
        文件夹名显示文本。
        扩展点：后续可接入 AI 对文件夹名做智能简化 / 翻译。
        """
        return f"名称：{folder_name}"

    @staticmethod
    def _fmt_product_label(product_name: str, full_code: str) -> str:
        """
        产品标签显示文本。
        扩展点：后续可接入 AI 对产品名/描述做摘要/翻译。
        """
        return f"描述：{product_name} ({full_code})"

    def _populate_list(self, results: list[dict]):
        """填充左侧结果列表。每项三行独立可复制：文件夹名/产品描述/69码。"""
        self.result_list.clear()
        self.btn_copy_codes.setVisible(False)

        if not results:
            item = QListWidgetItem("  无匹配结果")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.result_list.addItem(item)
            return

        has_codes = False
        for r in results:
            folder = r.get("folder_name", "")
            product = r.get("product_name", "")
            code = r.get("full_code", "")
            img_count = r.get("image_count", 0)
            folder_path = r.get("folder_path", "")

            # ── 行容器（点击非按钮区域 → 加载缩略图） ──
            row = QWidget()
            row.setCursor(Qt.CursorShape.PointingHandCursor)

            vbox = QVBoxLayout(row)
            vbox.setContentsMargins(6, 4, 6, 4)
            vbox.setSpacing(1)

            # 行1：文件夹名称 + 复制
            self._add_copy_row(vbox, "文件夹名称", folder)

            # 行2：产品描述（如有） + 复制
            if product:
                self._add_copy_row(vbox, "产品描述", product)
                has_codes = True
            else:
                # 无关联产品时显示图片数量
                self._add_info_row(vbox, f"图片数量：{img_count}" if img_count else "无关联产品")

            # 行3：69码（如有） + 复制
            if code:
                self._add_copy_row(vbox, "69码", code)
                has_codes = True

            # 嵌入到 QListWidgetItem — 计算正确高度
            vp_width = self.result_list.viewport().width()
            row.setFixedWidth(max(vp_width - 4, 240))
            hint = row.sizeHint()
            hint.setHeight(hint.height() + 6)
            item = QListWidgetItem()
            item.setSizeHint(hint)
            item.setData(Qt.ItemDataRole.UserRole, folder_path)
            self.result_list.addItem(item)
            self.result_list.setItemWidget(item, row)

            def _make_row_handler(_row, _fp, _item):
                def _handler(event):
                    child = _row.childAt(event.position().toPoint())
                    if child is not None:
                        if isinstance(child, QPushButton):
                            return
                        p = child.parent()
                        while p and p is not _row:
                            if isinstance(p, QPushButton):
                                return
                            p = p.parent()
                    self._on_item_click(_fp, _item)
                return _handler

            row.mousePressEvent = _make_row_handler(row, folder_path, item)

        self._all_codes = [r.get("full_code", "") for r in results if r.get("full_code")]
        self.btn_copy_codes.setVisible(has_codes)

    @staticmethod
    def _add_info_row(parent_layout: QVBoxLayout, text: str):
        """添加一行纯信息（不可复制）。"""
        label = QLabel(text)
        label.setObjectName("itemSubLabel")
        parent_layout.addWidget(label)

    @staticmethod
    def _add_copy_row(parent_layout: QVBoxLayout, label_text: str, value: str):
        """添加一行：标签 + 值 + 复制按钮。"""
        hbox = QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(4)

        lbl = QLabel(f"{label_text}：{value}")
        lbl.setWordWrap(True)
        lbl.setObjectName("itemFieldLabel")
        hbox.addWidget(lbl, 1)

        btn = QPushButton()
        btn.setFixedSize(22, 22)
        btn.setFlat(True)
        btn.setToolTip(f"复制{label_text}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setObjectName("copyBtn")
        btn.setIcon(SearchTab._copy_icon())
        btn.setIconSize(QSize(14, 14))
        btn.clicked.connect(lambda checked, v=value, b=btn: SearchTab._do_copy(v, b))
        hbox.addWidget(btn)

        parent_layout.addLayout(hbox)

    @staticmethod
    def _copy_icon() -> QIcon:
        """绘制复制图标（双矩形，中性灰适配暗/亮主题）。"""
        pix = QPixmap(28, 28)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 后方矩形（填充）
        p.setBrush(QColor(120, 130, 150))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(8, 1, 16, 18, 3, 3)
        # 前方矩形（填充 + 描边）
        p.setBrush(QColor(160, 170, 190))
        p.setPen(QPen(QColor(100, 110, 130), 2))
        p.drawRoundedRect(3, 7, 16, 18, 3, 3)
        p.end()
        return QIcon(pix)

    @staticmethod
    def _do_copy(text: str, btn: QPushButton | None = None):
        """复制文本到剪贴板，并在按钮旁显示提示。"""
        from PySide6.QtWidgets import QApplication as QA, QToolTip
        QA.clipboard().setText(text)
        if btn is not None:
            QToolTip.showText(btn.mapToGlobal(QPoint(0, -28)), "已复制！", btn)

    def _resolve_path(self, rel_path: str) -> str:
        """在多个 NAS 路径中查找第一个存在的完整路径。"""
        if os.path.isabs(rel_path):
            return rel_path if os.path.exists(rel_path) else ""
        for root in self._cfg.nas_root_paths:
            full = os.path.join(root, rel_path)
            if os.path.exists(full):
                return full
        # 回退到第一个路径
        if self._cfg.nas_root_paths:
            return os.path.join(self._cfg.nas_root_paths[0], rel_path)
        return rel_path

    def _on_item_click(self, folder_path: str, item: QListWidgetItem | None = None):
        """点击列表项 → 高亮行 + 加载缩略图 + 显示路径。"""
        if not folder_path:
            return
        if item is not None:
            self.result_list.setCurrentItem(item)
            self._highlight_row(item)
        full = self._resolve_path(folder_path)
        self.path_bar.setText(full or folder_path)
        self._load_thumbnails(folder_path)

    # ── 复制行为 ──────────────────────────────────────────────────
    def _on_copy_all_codes(self):
        """复制当前列表所有69码（换行分隔）。"""
        if self._all_codes:
            from PySide6.QtWidgets import QApplication as QA
            QA.clipboard().setText("\n".join(self._all_codes))
            self.status_label.setText(f"已复制 {len(self._all_codes)} 个69码")
        else:
            self.status_label.setText("无69码可复制")

    # ── 路径条 ────────────────────────────────────────────────────

    def _on_path_bar_click(self, _event):
        """点击路径条 → 复制到剪贴板。"""
        text = self.path_bar.text()
        if text and text != "请选择左侧结果":
            from PySide6.QtWidgets import QApplication as QA
            QA.clipboard().setText(text)
            self.status_label.setText("路径已复制")

    # ── 缩略图网格 ────────────────────────────────────────────────
    def _show_placeholder_right(self):
        """清空右侧并显示占位提示。"""
        self._clear_thumb_grid()
        hint = QLabel("选择左侧结果\n查看对应图片")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setProperty("placeholderRole", "title")
        self.thumb_grid.addWidget(hint, 0, 0)

    def _clear_thumb_grid(self):
        """清空缩略图网格。"""
        while self.thumb_grid.count():
            child = self.thumb_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _load_thumbnails(self, folder_path: str):
        """同步加载缩略图（setScaledSize 已很快，processEvents 防卡顿）。"""
        if folder_path in self._thumb_cache:
            self._render_thumb_grid(self._thumb_cache[folder_path])
            return

        images = self._db.get_images_by_folder(folder_path)
        if not images:
            self.status_label.setText("该文件夹无图片")
            return

        pixmaps = []
        for i, img in enumerate(images):
            full_path = img["full_unc"]
            if not os.path.isabs(full_path):
                full_path = self._resolve_path(full_path)
            reader = QImageReader(full_path)
            reader.setAutoTransform(True)
            reader.setScaledSize(QSize(200, 160))
            pix = QPixmap.fromImageReader(reader)
            pixmaps.append((pix if not pix.isNull() else QPixmap(), img))
            # 每 5 张让事件循环喘口气，UI 不冻结
            if i % 5 == 0:
                QApplication.processEvents()

        if len(self._thumb_cache) >= 3:
            oldest = next(iter(self._thumb_cache))
            del self._thumb_cache[oldest]
        self._thumb_cache[folder_path] = pixmaps

        self._render_thumb_grid(pixmaps)
        self.status_label.setText(f"{len(images)} 张图片")

    def _render_thumb_grid(self, pixmaps: list):
        """渲染缩略图到网格（单列）。"""
        self._clear_thumb_grid()
        for i, (pix, img) in enumerate(pixmaps):

            container = QWidget()
            container.setObjectName("thumbItem")
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(2, 2, 2, 2)
            vbox.setSpacing(2)

            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_label.setFixedSize(200, 160)
            if not pix.isNull():
                thumb_label.setPixmap(pix)
            else:
                thumb_label.setText("🖼️\n无法加载")
                thumb_label.setProperty("placeholderRole", "title")
            thumb_label.setObjectName("thumbImage")
            vbox.addWidget(thumb_label, alignment=Qt.AlignmentFlag.AlignCenter)

            # 文件名标签
            fname = img.get("file_name", "") if isinstance(img, dict) else ""
            name_label = QLabel(fname if len(fname) <= 18 else fname[:16] + "…")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setObjectName("thumbFileName")
            name_label.setWordWrap(False)
            vbox.addWidget(name_label, alignment=Qt.AlignmentFlag.AlignCenter)

            # 点击打开文件夹位置
            folder = img.get("folder_path", "") if isinstance(img, dict) else ""
            thumb_label.setToolTip(f"点击打开文件夹: {folder}")
            thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb_label._folder_path = folder
            thumb_label.mousePressEvent = (
                lambda e, p=folder: self._open_folder(p)
            )

            self.thumb_grid.addWidget(container, i, 0)

    def _open_folder(self, folder_path: str):
        """在资源管理器中打开文件夹。"""
        if not folder_path:
            return
        full = self._resolve_path(folder_path)
        if full and os.path.exists(full):
            os.startfile(full)

    # ── 工具栏按钮事件 ──────────────────────────────────────────────
    def _on_import_products(self):
        """打开 Excel 导入对话框。"""
        dlg = ImportDialog(self._db, self)
        if dlg.exec() == ImportDialog.DialogCode.Accepted:
            self.status_changed.emit()

    def _on_incremental_scan(self):
        """增量扫描 — 仅处理上次扫描后的新文件。"""
        self._start_scan(incremental=True)

    def _on_full_scan(self):
        """全量重建索引 — 清空旧数据后重新扫描。"""
        reply = QMessageBox.question(
            self,
            "确认重建索引",
            "将清空所有图片索引数据并重新扫描。\n"
            "现有的产品数据不受影响。\n\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._start_scan(incremental=False)

    def _on_open_settings(self):
        """打开设置对话框。"""
        dlg = SettingsDialog(self._db, self._cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.status_changed.emit()

    def _start_scan(self, incremental: bool):
        """启动后台扫描线程（支持多 NAS 路径）。"""
        running = False
        if self._scan_thread is not None:
            try:
                running = self._scan_thread.isRunning()
            except RuntimeError:
                pass
        if running:
            QMessageBox.information(self, "扫描进行中", "上一次扫描尚未完成，请等待完成后再试。")
            return

        self._scan_thread = None
        self._scan_worker = None

        paths = self._cfg.nas_root_paths
        if not paths:
            QMessageBox.information(
                self, "未配置 NAS 路径",
                "尚未配置 NAS 图片根目录。\n\n"
                "请点击工具栏右侧的 ⚙️ 按钮打开设置，选择图片所在的根目录后再进行扫描。"
            )
            return

        # 全量扫描前清空索引
        if not incremental:
            self._db.clear_index()

        self._set_buttons_enabled(False)
        self.status_label.setText("扫描中…")

        times = {}
        if incremental:
            for p in paths:
                times[p] = self._cfg.get_scan_time(p)

        self._scan_worker = ScanWorker(
            self._db, paths,
            incremental=incremental,
            last_scan_times=times,
        )
        self._scan_thread = ScanThread(self._scan_worker)
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.path_label.connect(self._on_scan_path)
        self._scan_worker.status_message.connect(self._on_scan_status)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)

        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.finished.connect(self._scan_worker.deleteLater)

        self._scan_thread.start()

    def _on_scan_path(self, label: str):
        """当前扫描的路径标签。"""
        self.status_label.setText(f"扫描 {label}")

    def _on_scan_progress(self, current: int, total: int):
        self.status_label.setText(f"{self.status_label.text().split(' —')[0]} — {current}/{total}")

    def _on_scan_status(self, msg: str):
        self.status_label.setText(msg)

    def _on_scan_finished(self, stats: dict):
        self._set_buttons_enabled(True)
        import time
        for p in self._cfg.nas_root_paths:
            self._cfg.set_scan_time(p, time.time())
        files = stats.get("files", 0)
        folders = stats.get("folders", 0)
        linked = stats.get("linked", 0)
        self.status_label.setText(
            f"扫描完成：{files} 张图片, {folders} 个文件夹, {linked} 组关联"
        )
        self.status_changed.emit()

    def _on_scan_error(self, msg: str):
        self._set_buttons_enabled(True)
        self.status_label.setText(f"错误: {msg}")
        QMessageBox.critical(self, "扫描失败", msg)

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_import.setEnabled(enabled)
        self.btn_inc_scan.setEnabled(enabled)
        self.btn_full_scan.setEnabled(enabled)
        self.btn_settings.setEnabled(enabled)

    def refresh_status(self):
        """更新内部状态标签。"""
        product_count = self._db.get_product_count()
        image_count = self._db.get_image_count()
        if image_count > 0:
            folder_count = self._db.get_folder_count()
            self.status_label.setText(
                f"{image_count} 张图片, {folder_count} 个文件夹"
            )
        elif product_count > 0:
            self.status_label.setText(f"就绪 ({product_count} 个产品)")
        else:
            self.status_label.setText("就绪 — 请导入产品或扫描目录")

