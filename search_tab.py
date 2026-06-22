"""
检索标签页 — v2.0 产品优先布局。

左侧：产品卡片列表（69码 + 主图缩略图 + 名称 + 分类标签）
右侧：图片浏览 + 产品信息 + 可折叠规格
"""
import os, re
from PySide6.QtCore import Qt, QPoint, QSize, QThread, QTimer, Signal
from PySide6.QtGui import (
    QIcon, QImageReader, QPixmap, QPainter, QColor, QFont, QPen, QBrush,
    QAction, QCursor,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QToolTip,
    QVBoxLayout, QWidget, QMenu, QFrame,
)

from config import Config
from database import Database
from import_dialog import ImportDialog
from scanner import ScanWorker, ScanThread
from widgets import Card, Placeholder
from settings_dialog import SettingsDialog


# ── 常量 ─────────────────────────────────────────────────────────
THUMB_SIZE = 120          # 产品卡片缩略图
GALLERY_SIZE = 220        # 右侧图片浏览缩略图
CARD_HEIGHT = THUMB_SIZE + 16  # 8px padding × 2
SEARCH_DEBOUNCE_MS = 400


def _resolve_path(relative: str, nas_root: str) -> str:
    """将相对路径拼接 NAS 根目录；已绝对路径则直接返回。"""
    if not relative:
        return ""
    if os.path.isabs(relative):
        return relative
    if nas_root:
        return os.path.join(nas_root, relative)
    return relative  # 无 nas_root 时保持原样（调用方检查存在性）


def _safe_open_folder(path: str, nas_root: str = ""):
    """安全打开文件夹：拼接路径 → 检查存在 → 打开。"""
    full = _resolve_path(path, nas_root)
    if full and os.path.isdir(full):
        os.startfile(full)
    elif full and os.path.isfile(full):
        os.startfile(os.path.dirname(full))


def _safe_open_file(path: str, nas_root: str = ""):
    """安全打开文件：拼接路径 → 检查存在 → 用默认程序打开。"""
    full = _resolve_path(path, nas_root)
    if full and os.path.isfile(full):
        os.startfile(full)


# ═══════════════════════════════════════════════════════════════════
# SearchBar — 极简搜索输入框
# ═══════════════════════════════════════════════════════════════════
class SearchBar(QWidget):
    """搜索栏：输入框 + 模式标签 + 清除按钮。"""

    search_triggered = Signal(str)
    clear_triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("searchBar")
        self._mode = "idle"  # idle / code / keyword / image / intersect

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # 模式标签
        self.mode_tag = QLabel("")
        self.mode_tag.setObjectName("modeTag")
        self.mode_tag.setFixedHeight(28)
        self.mode_tag.setVisible(False)
        layout.addWidget(self.mode_tag)

        # 搜索图标
        icon = QLabel("🔍")
        icon.setFixedWidth(20)
        icon.setStyleSheet("font-size: 14px;")
        layout.addWidget(icon)

        # 输入框
        self.input = QLineEdit()
        self.input.setObjectName("searchInput")
        self.input.setPlaceholderText("输入69码/关键词，或拖图片到此处…")
        self.input.setFixedHeight(40)
        self.input.setAcceptDrops(True)
        layout.addWidget(self.input, 1)

        # 清除按钮
        self.btn_clear = QPushButton("×")
        self.btn_clear.setObjectName("clearBtn")
        self.btn_clear.setFixedSize(28, 28)
        self.btn_clear.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_clear.setToolTip("清空搜索")
        self.btn_clear.clicked.connect(self._clear)
        self.btn_clear.setVisible(False)
        layout.addWidget(self.btn_clear)

        # 防抖定时器
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self._emit_search)

        self.input.textChanged.connect(self._on_text_changed)
        self.input.returnPressed.connect(self._emit_search)

    def _on_text_changed(self, text: str):
        self.btn_clear.setVisible(bool(text))
        self._timer.start()
        # 更新模式标签
        if not text.strip():
            self._set_mode("idle")
        elif text.strip().isdigit():
            self._set_mode("code")
        else:
            self._set_mode("keyword")

    def _emit_search(self):
        self._timer.stop()
        self.search_triggered.emit(self.input.text().strip())

    def _clear(self):
        self.input.clear()
        self.clear_triggered.emit()

    def _set_mode(self, mode: str):
        self._mode = mode
        tag_map = {
            "idle": ("", ""),
            "code": ("69码", "#4FC3F7"),
            "keyword": ("关键词", "#81C784"),
            "image": ("以图搜图", "#CE93D8"),
            "intersect": ("交集", "#FFB74D"),
        }
        text, color = tag_map.get(mode, ("", ""))
        if text:
            self.mode_tag.setText(text)
            self.mode_tag.setStyleSheet(
                f"background:{color}22; color:{color}; "
                f"border:1px solid {color}44; border-radius:4px; "
                f"padding:2px 8px; font-size:11px; font-weight:bold;"
            )
            self.mode_tag.setVisible(True)
        else:
            self.mode_tag.setVisible(False)


# ═══════════════════════════════════════════════════════════════════
# ProductCard — 单张产品卡片
# ═══════════════════════════════════════════════════════════════════
class ProductCard(QFrame):
    """左侧产品卡片 — 缩略图 + 69码 + 名称 + 分类标签。"""

    clicked = Signal(dict)       # 单击 → 选中
    double_clicked = Signal(str)  # 双击 → 打开文件夹

    def __init__(self, product: dict, nas_root: str = "", parent=None):
        super().__init__(parent)
        self._product = product
        self._nas_root = nas_root
        self._selected = False
        self.setObjectName("productCard")
        self.setFixedHeight(CARD_HEIGHT)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._setup_ui()
        self._load_thumbnail()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # ── 左：缩略图 ──
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setObjectName("cardThumb")
        layout.addWidget(self.thumb)

        # ── 右：文字信息 ──
        text_box = QVBoxLayout()
        text_box.setSpacing(2)

        # 69码行
        code_row = QHBoxLayout()
        code_row.setSpacing(6)
        code_label = QLabel(self._product.get("full_code", ""))
        code_label.setObjectName("cardCode")
        code_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        code_label.mousePressEvent = lambda e: self._copy_code()
        code_row.addWidget(code_label)

        btn_copy = QPushButton("📋")
        btn_copy.setObjectName("cardCopyBtn")
        btn_copy.setFixedSize(22, 22)
        btn_copy.setToolTip("复制69码")
        btn_copy.clicked.connect(self._copy_code)
        code_row.addWidget(btn_copy)
        code_row.addStretch()
        text_box.addLayout(code_row)

        # 产品名
        name = QLabel(self._product.get("name", ""))
        name.setObjectName("cardName")
        name.setWordWrap(True)
        name.setMaximumHeight(36)
        text_box.addWidget(name)

        # 分类标签
        category = self._product.get("category", "")
        if category:
            tag = QLabel(f"🏷️ {category}")
            tag.setObjectName("cardTag")
            text_box.addWidget(tag)

        # 规格摘要（如有）
        specs = self._product.get("specs_summary", "")
        if specs:
            spec_label = QLabel(specs)
            spec_label.setObjectName("cardSpecs")
            text_box.addWidget(spec_label)

        text_box.addStretch()
        layout.addLayout(text_box, 1)

    def _load_thumbnail(self):
        """从NAS加载产品主图缩略图。"""
        image_path = self._product.get("main_image_path", "")
        if image_path and os.path.isfile(image_path):
            reader = QImageReader(image_path)
            reader.setAutoTransform(True)
            reader.setScaledSize(QSize(THUMB_SIZE, THUMB_SIZE))
            pix = QPixmap.fromImageReader(reader)
            if not pix.isNull():
                self.thumb.setPixmap(pix)
                return
        # 占位
        self.thumb.setText("🖼️")
        self.thumb.setStyleSheet("font-size: 32px; color: #45475a;")

    def _copy_code(self):
        code = self._product.get("full_code", "")
        if code:
            QApplication.clipboard().setText(code)
            QToolTip.showText(self.mapToGlobal(QPoint(0, -28)), f"已复制 {code}", self)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._product)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        folder = self._product.get("folder_path", "")
        if folder:
            self.double_clicked.emit(_resolve_path(folder, self._nas_root))
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_copy = QAction("📋 复制69码")
        act_copy.triggered.connect(self._copy_code)
        menu.addAction(act_copy)
        folder = self._product.get("folder_path", "")
        if folder:
            act_open = QAction("📁 打开文件夹")
            act_open.triggered.connect(
                lambda f=_resolve_path(folder, self._nas_root): self.double_clicked.emit(f)
            )
            menu.addAction(act_open)
        menu.exec(event.globalPos())


# ═══════════════════════════════════════════════════════════════════
# ProductList — 左侧产品卡片列表
# ═══════════════════════════════════════════════════════════════════
class ProductList(QWidget):
    """产品卡片列表 + 底部计数 + 复制全部按钮。"""

    product_selected = Signal(dict)
    product_double_clicked = Signal(str)
    count_changed = Signal(int)

    def __init__(self, nas_root: str = "", parent=None):
        super().__init__(parent)
        self._nas_root = nas_root
        self._cards: list[ProductCard] = []
        self._all_codes: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 卡片列表
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("productCardList")
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list_widget.setSpacing(2)
        layout.addWidget(self.list_widget, 1)

        # 底部栏
        footer = QWidget()
        footer.setObjectName("listFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 6, 12, 6)
        footer_layout.setSpacing(8)

        self.count_label = QLabel("")
        self.count_label.setObjectName("listCount")
        footer_layout.addWidget(self.count_label)
        footer_layout.addStretch()

        self.btn_copy_all = QPushButton("📋 复制全部69码")
        self.btn_copy_all.setObjectName("copyAllBtn")
        self.btn_copy_all.setToolTip("复制当前列表所有69码（换行分隔）")
        self.btn_copy_all.clicked.connect(self._copy_all)
        self.btn_copy_all.setVisible(False)
        footer_layout.addWidget(self.btn_copy_all)

        layout.addWidget(footer)

    def set_products(self, products: list[dict]):
        """填充产品卡片列表。"""
        self.list_widget.clear()
        self._cards.clear()
        self._all_codes.clear()

        if not products:
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty = QLabel("  无匹配结果")
            empty.setObjectName("cardName")
            empty.setStyleSheet("padding:20px;")
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, empty)
            self.count_label.setText("")
            self.btn_copy_all.setVisible(False)
            self.count_changed.emit(0)
            return

        for p in products:
            card = ProductCard(p, self._nas_root)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            self._cards.append(card)

            item = QListWidgetItem()
            item.setSizeHint(QSize(0, CARD_HEIGHT + 4))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

        # 选中第一个
        if self._cards:
            self._cards[0].set_selected(True)
            self._selected_card = self._cards[0]
            self.product_selected.emit(products[0])

        self._all_codes = [p.get("full_code", "") for p in products if p.get("full_code")]
        self.btn_copy_all.setVisible(len(self._all_codes) > 1)
        self.count_label.setText(f"找到 {len(products)} 个产品")
        self.count_changed.emit(len(products))

    def _on_card_clicked(self, product: dict):
        for c in self._cards:
            c.set_selected(False)
        sender = self.sender()
        if isinstance(sender, ProductCard):
            sender.set_selected(True)
            self._selected_card = sender
        self.product_selected.emit(product)

    def _on_card_double_clicked(self, path: str):
        self.product_double_clicked.emit(path)

    def _copy_all(self):
        if self._all_codes:
            QApplication.clipboard().setText("\n".join(self._all_codes))
            self.count_label.setText(f"已复制 {len(self._all_codes)} 个69码")
            QTimer.singleShot(2000, lambda: self.count_label.setText(
                f"找到 {len(self._cards)} 个产品"
            ))

    def clear(self):
        self.set_products([])

    def set_nas_root(self, path: str):
        self._nas_root = path


# ── 工具函数 ─────────────────────────────────────────────────────
def _guess_image_set(folder_name: str) -> str:
    """从文件夹名猜测 image_set 类型标签。"""
    mapping = {
        "中文": "中文", "英语": "英语", "英文": "英语",
        "西班牙语": "西语", "俄语": "俄语", "韩语": "韩语",
        "印尼语": "印尼", "泰语": "泰语", "法文": "法语",
        "渲染图": "渲染", "实拍图": "实拍",
        "主图": "主图", "详情": "详情",
        "亚马逊": "亚马逊", "停售": "停售", "停用": "停售",
        "暂未售": "停售",
    }
    for key, label in mapping.items():
        if key in folder_name:
            return label
    return ""


def _extract_category(name: str) -> str:
    """从产品名称提取分类标签。"""
    keywords = [
        "转接卡", "延长线", "硬盘盒", "数据线", "风扇", "水晶头",
        "模块", "护套", "散热", "支架", "网卡", "阵列卡", "增高卡",
        "拆分卡", "网线钳", "分配器", "采集卡", "转接线", "转换头",
        "投屏线", "快充", "供电线", "转接板", "螺丝刀", "螺母",
        "网络模块", "剥线刀", "水晶头护套",
    ]
    for kw in keywords:
        if kw in name:
            return kw
    return ""


def _extract_specs_from_name(name: str) -> dict:
    """从产品名称中提取常见规格键值对。"""
    specs = {}
    # PCIe 版本
    import re
    m = re.search(r'PCIE?\s*(\d+\.?\d*)', name, re.IGNORECASE)
    if m:
        specs["接口版本"] = f"PCIe {m.group(1)}"
    # 转接方向: M.2 / SATA / NVMe / X1 / X4 / X16
    for k in ["M.2", "NVMe", "SATA", "X16", "X4", "X1"]:
        if k in name:
            specs.setdefault("规格", k)
    # 尺寸: 2280 / 2242 / 2230 / 22110
    m2 = re.search(r'(22\d{2}|22110)', name)
    if m2:
        specs["支持尺寸"] = m2.group(1)
    # 长度: 25CM / 50CM
    m3 = re.search(r'(\d+)CM', name, re.IGNORECASE)
    if m3:
        specs["线长"] = f"{m3.group(1)}CM"
    # 颜色
    for color in ["黑色", "白色", "红色", "蓝色", "绿色", "黄色", "青色", "灰色"]:
        if color in name:
            specs["颜色"] = color
            break
    return specs


# ═══════════════════════════════════════════════════════════════════
# RightPanel — 产品工作台
# ═══════════════════════════════════════════════════════════════════
class RightPanel(QWidget):
    """右侧产品工作台：固定身份条 + 可滚动卡片区域。

    卡片从上到下：
      ① 产品身份条（固定）- 69码 + 名称 + 操作按钮
      ② 规格参数卡片 - 产品属性（动态，按 spec_group 分组）
      ③ 产品图片卡片 - 缩略图网格
      ④ AI 工作台卡片（未来）
    """

    open_folder_requested = Signal(str)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.setObjectName("rightPanel")
        self._product: dict = {}
        self._nas_root = ""
        self._images: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── ① ProductIdentityBar（固定顶部） ──
        self.identity = ProductIdentityBar()
        self.identity.open_folder_requested.connect(self.open_folder_requested)
        layout.addWidget(self.identity)

        # ── 可滚动卡片区域 ──
        self.scroll = QScrollArea()
        self.scroll.setObjectName("rightScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("scrollContent")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 12)
        self.scroll_layout.setSpacing(8)

        # ── ② SpecsCard（产品详情优先） ──
        self.specs_card = SpecsCard()
        self.scroll_layout.addWidget(self.specs_card)

        # ── ③ ImageCard（图片在下方） ──
        self.image_card = ImageCard()
        self.image_card.open_image_requested.connect(self._on_open_image)
        self.image_card.open_folder_requested.connect(self.open_folder_requested)
        self.scroll_layout.addWidget(self.image_card)

        # ── ④ AICard（未来：阶段 7） ──
        self.ai_card = AICard()
        self.scroll_layout.addWidget(self.ai_card)

        self.scroll_layout.addStretch()
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll, 1)

    def show_empty(self):
        self.identity.clear()
        self.specs_card.clear()
        self.image_card.clear()
        self.ai_card.clear()

    def set_product(self, product: dict, images: list[dict], nas_root: str = ""):
        self._product = product
        self._nas_root = nas_root
        self._images = images

        pid = product.get("product_id")

        self.identity.set_product(product, nas_root)
        # 动态规格：从 product_specs 表读取
        specs = self._db.get_product_specs(pid) if pid else []
        self.specs_card.set_specs(specs, product)
        # 图片
        self.image_card.set_images(images, nas_root)
        self.ai_card.set_product(product)

    def _on_open_image(self, path: str):
        _safe_open_file(path)


# ── ① ProductIdentityBar ─────────────────────────────────────────
class ProductIdentityBar(QWidget):
    """产品身份条：69码 + 名称 + 分类 + 操作按钮。"""

    open_folder_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("identityBar")
        self.setFixedHeight(80)
        self._full_code = ""
        self._folder_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(6)

        # 行1：69码 + 名称
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.code_label = QLabel("")
        self.code_label.setObjectName("identityCode")
        self.code_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.code_label.mousePressEvent = lambda e: self._copy("69码", self._full_code)
        row1.addWidget(self.code_label)

        self.name_label = QLabel("")
        self.name_label.setObjectName("identityName")
        self.name_label.setWordWrap(True)
        row1.addWidget(self.name_label, 1)

        self.cat_label = QLabel("")
        self.cat_label.setObjectName("identityCat")
        row1.addWidget(self.cat_label)
        layout.addLayout(row1)

        # 行2：文件夹路径 + 操作按钮
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self.path_label = QLabel("")
        self.path_label.setObjectName("identityPath")
        self.path_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.path_label.mousePressEvent = lambda e: self._copy("路径", self.path_label.toolTip() or self.path_label.text())
        row2.addWidget(self.path_label, 1)

        for text, slot, tip in [
            ("📂 打开", self._open_folder, "打开文件夹"),
            ("📋 69码", lambda: self._copy("69码", self._full_code), "复制69码"),
            ("📋 名称", lambda: self._copy("名称", self.name_label.text()), "复制产品名称"),
            ("📐 规格", self._copy_specs, "复制规格参数"),
        ]:
            btn = QPushButton(text)
            btn.setObjectName("identityBtn")
            btn.setFixedHeight(26)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            row2.addWidget(btn)

        layout.addLayout(row2)

    def set_product(self, product: dict, nas_root: str = ""):
        self._full_code = product.get("full_code", "")
        self._folder_path = product.get("folder_path", "")
        name = product.get("name", "")
        category = product.get("category", "")

        full_path = _resolve_path(self._folder_path, nas_root)

        self.code_label.setText(self._full_code)
        self.name_label.setText(name)
        self.cat_label.setText(f"🏷️ {category}" if category else "")
        display = full_path if len(full_path) <= 70 else "…" + full_path[-67:]
        self.path_label.setText(display)
        self.path_label.setToolTip(full_path)

    def _open_folder(self):
        if self._folder_path:
            self.open_folder_requested.emit(self._folder_path)

    def _copy(self, label: str, text: str):
        if text:
            QApplication.clipboard().setText(text)
            QToolTip.showText(self.mapToGlobal(QPoint(0, -28)), f"已复制 {label}", self)

    def _copy_specs(self):
        """复制规格摘要到剪贴板。"""
        parent = self.parent()
        # 向上查找 RightPanel 获取 specs_card
        while parent and not isinstance(parent, RightPanel):
            parent = parent.parent()
        if parent and hasattr(parent, 'specs_card'):
            specs_text = parent.specs_card.get_specs_text()
            if specs_text:
                QApplication.clipboard().setText(specs_text)
                QToolTip.showText(self.mapToGlobal(QPoint(0, -28)), "已复制规格", self)

    def clear(self):
        self.code_label.setText("")
        self.name_label.setText("")
        self.cat_label.setText("")
        self.path_label.setText("点击左侧产品查看详情")
        self._full_code = ""
        self._folder_path = ""


# ── ② ImageCard ──────────────────────────────────────────────────
class ImageCard(QWidget):
    """产品图片卡片：按 image_set 分组展示缩略图。"""

    open_image_requested = Signal(str)
    open_folder_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("imageCard")
        self._nas_root = ""
        self._images: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # 标题
        header = QHBoxLayout()
        title = QLabel("📷 产品图片")
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch()
        self.count_label = QLabel("")
        self.count_label.setObjectName("cardCount")
        header.addWidget(self.count_label)
        layout.addLayout(header)

        # 图片网格
        self.grid_widget = QWidget()
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.grid_widget)

    def set_images(self, images: list[dict], nas_root: str = ""):
        self._clear_grid()
        self._nas_root = nas_root
        self._images = images

        if not images:
            self.count_label.setText("暂无图片")
            empty = QLabel("该产品暂未关联图片\n请先导入产品并扫描图片目录")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setProperty("placeholderRole", "desc")
            self.grid.addWidget(empty, 0, 0)
            return

        self.count_label.setText(f"{len(images)} 张")

        # 按 image_set 分组排序：中文/英语优先
        priority_order = {"中文": 0, "英语": 1, "主图": 2, "实拍图": 3, "渲染图": 4}
        sorted_images = sorted(images, key=lambda i: priority_order.get(
            _guess_image_set(i.get("folder_name", "")), 99
        ))

        # 计算列数（自适应）
        parent_width = self.width()
        cols = max(2, (parent_width - 56) // (GALLERY_SIZE + 8))

        for i, img in enumerate(sorted_images):
            w = self._make_thumb(img)
            row, col = i // cols, i % cols
            self.grid.addWidget(w, row, col, Qt.AlignmentFlag.AlignTop)

    def _make_thumb(self, img: dict) -> QWidget:
        full_unc = img.get("full_unc", "")
        folder_path = img.get("folder_path", "")
        folder_name = img.get("folder_name", "")
        file_name = img.get("file_name", "")
        set_type = _guess_image_set(folder_name)

        container = QWidget()
        container.setFixedSize(GALLERY_SIZE + 4, GALLERY_SIZE + 22)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(2, 2, 2, 0)
        vbox.setSpacing(1)

        # 缩略图
        thumb = QLabel()
        thumb.setFixedSize(GALLERY_SIZE, GALLERY_SIZE)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setObjectName("cardThumb")
        thumb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        path = _resolve_path(full_unc, self._nas_root)
        if os.path.isfile(path):
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            reader.setScaledSize(QSize(GALLERY_SIZE, GALLERY_SIZE))
            pix = QPixmap.fromImageReader(reader)
            if not pix.isNull():
                thumb.setPixmap(pix)
            else:
                thumb.setText("🖼️")
                thumb.setProperty("placeholderRole", "icon")
        else:
            thumb.setText("📁")
            thumb.setProperty("placeholderRole", "icon")

        # 交互
        resolved = path
        thumb.mouseDoubleClickEvent = lambda e, p=resolved: self.open_image_requested.emit(p)
        thumb.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        thumb.customContextMenuRequested.connect(
            lambda pos, p=resolved, fp=folder_path: self._context_menu(pos, p, fp)
        )
        vbox.addWidget(thumb)

        # 角标
        if set_type:
            badge = QLabel(set_type, container)
            badge.setObjectName("galleryBadge")
            badge.setGeometry(GALLERY_SIZE - 50, GALLERY_SIZE - 18, 48, 16)

        return container

    def _context_menu(self, pos, full_path: str, folder_path: str):
        menu = QMenu(self)
        if full_path and os.path.isfile(full_path):
            menu.addAction("🖼️ 打开原图", lambda p=full_path: _safe_open_file(p))
        if folder_path:
            menu.addAction("📁 打开文件夹", lambda fp=folder_path: self.open_folder_requested.emit(fp))
        menu.addAction("📋 复制路径", lambda t=full_path: QApplication.clipboard().setText(t))
        menu.exec(self.mapToGlobal(pos))

    def _clear_grid(self):
        while self.grid.count():
            child = self.grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def clear(self):
        self._clear_grid()
        self.count_label.setText("")
        self._images = []


# ── ② SpecsCard（动态规格，详情优先） ──────────────────────────
class SpecsCard(QWidget):
    """规格参数卡片 — 完全动态：从 product_specs 表读取，按 spec_group 分组。

    不硬编码任何规格字段。知识库 (JSONL) 或 CSV 导入什么就展示什么。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("specsCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        title = QLabel("📋 产品详情")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.content = QVBoxLayout()
        self.content.setSpacing(4)
        layout.addLayout(self.content)

    def set_specs(self, specs: list[dict], product: dict = None):
        self._clear()
        product = product or {}

        # 从 product_specs 表读取（动态 + 分组）
        if specs:
            groups: dict[str, list[dict]] = {}
            for s in specs:
                g = s.get("group", "基本规格")
                groups.setdefault(g, []).append(s)

            for group_name, items in groups.items():
                # 分组标题
                group_label = QLabel(_spec_group_icon(group_name) + " " + group_name)
                group_label.setObjectName("specGroupTitle")
                self.content.addWidget(group_label)

                for item in items:
                    self._add_spec_row(item["name"], item["value"], item.get("source", ""))
        else:
            # 无规格时尝试从名称提取 + 提示
            name = product.get("name", "")
            extracted = _extract_specs_from_name(name)
            if extracted:
                group_label = QLabel("📐 自动识别")
                group_label.setObjectName("specGroupTitle")
                self.content.addWidget(group_label)
                for k, v in extracted.items():
                    self._add_spec_row(k, v, "auto")

            hint = QLabel("导入 CSV 或知识库后可显示完整规格")
            hint.setObjectName("specsEmpty")
            self.content.addWidget(hint)

        self.content.addStretch()

    def _add_spec_row(self, name: str, value: str, source: str = ""):
        row = QHBoxLayout()
        row.setSpacing(10)
        k = QLabel(name)
        k.setObjectName("specKey")
        k.setFixedWidth(90)
        row.addWidget(k)
        v = QLabel(value)
        v.setObjectName("specValue")
        v.setWordWrap(True)
        v.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        v.mousePressEvent = lambda e, val=value, lbl=v: (
            QApplication.clipboard().setText(val),
            QToolTip.showText(lbl.mapToGlobal(QPoint(0, -24)), f"已复制 {val}", lbl)
        )
        row.addWidget(v, 1)
        self.content.addLayout(row)

    def get_specs_text(self) -> str:
        lines = []
        for i in range(self.content.count()):
            item = self.content.itemAt(i)
            w = item.widget()
            if isinstance(w, QLabel) and w.objectName() == "specGroupTitle":
                lines.append(f"\n【{w.text()}】")
            elif isinstance(item, QHBoxLayout):
                kids = []
                for j in range(item.count()):
                    cw = item.itemAt(j).widget()
                    if isinstance(cw, QLabel):
                        kids.append(cw.text())
                if len(kids) >= 2:
                    lines.append(f"{kids[0]}：{kids[1]}")
        return "\n".join(lines).strip()

    def _clear(self):
        while self.content.count():
            child = self.content.takeAt(0)
            if isinstance(child, QHBoxLayout):
                while child.count():
                    sub = child.takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
            elif child.widget():
                child.widget().deleteLater()

    def clear(self):
        self._clear()


def _spec_group_icon(group: str) -> str:
    icons = {"物理参数": "📐", "报关信息": "🛃", "基本规格": "📦",
             "接口": "🔌", "性能": "⚡"}
    return icons.get(group, "📌")


# ── ④ AICard（未来：阶段 7）──────────────────────────────────────
class AICard(QWidget):
    """AI 工作台卡片 — 知识库就绪后激活。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        title = QLabel("🤖 AI 工作台")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        hint = QLabel("知识库就绪后，此处可：\n"
                      "· 一键生成英文/西班牙语产品描述\n"
                      "· 提取产品卖点与标题优化\n"
                      "· 根据截图 + 产品信息智能回复客户\n"
                      "（阶段 7：LLM 产品分析脚本完成后激活）")
        hint.setObjectName("aiHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def set_product(self, product: dict):
        pass  # 未来：根据产品启用 AI 功能按钮

    def clear(self):
        pass


# ═══════════════════════════════════════════════════════════════════
# SearchTab — 主检索标签页
# ═══════════════════════════════════════════════════════════════════
class SearchTab(QWidget):
    """📦 图片检索 — 产品优先布局。"""

    status_changed = Signal()

    def __init__(self, database: Database, config: Config, parent=None):
        super().__init__(parent)
        self._db = database
        self._cfg = config
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._current_products: list[dict] = []
        self._current_product: dict | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 搜索栏 ──
        self.search_bar = SearchBar()
        self.search_bar.search_triggered.connect(self._on_search)
        self.search_bar.clear_triggered.connect(self._on_clear)
        layout.addWidget(self.search_bar)

        # ── 工具栏（精简） ──
        toolbar = QWidget()
        toolbar.setObjectName("searchToolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(14, 4, 14, 4)
        tb_layout.setSpacing(6)

        btn_import = QPushButton("📥 导入CSV")
        btn_import.setToolTip("从CSV/Excel导入产品数据")
        btn_import.setProperty("toolbarButton", "yes")
        btn_import.clicked.connect(self._on_import_products)
        tb_layout.addWidget(btn_import)

        btn_scan = QPushButton("🔄 增量扫描")
        btn_scan.setToolTip("扫描新增图片")
        btn_scan.setProperty("toolbarButton", "yes")
        btn_scan.clicked.connect(self._on_incremental_scan)
        tb_layout.addWidget(btn_scan)

        btn_full = QPushButton("🔁 重建索引")
        btn_full.setToolTip("全量重建索引")
        btn_full.setProperty("toolbarButton", "yes")
        btn_full.clicked.connect(self._on_full_scan)
        tb_layout.addWidget(btn_full)

        tb_layout.addStretch()

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("searchStatusLabel")
        tb_layout.addWidget(self.status_label)

        btn_settings = QPushButton("⚙️")
        btn_settings.setToolTip("设置")
        btn_settings.setProperty("toolbarButton", "yes")
        btn_settings.clicked.connect(self._on_open_settings)
        tb_layout.addWidget(btn_settings)

        layout.addWidget(toolbar)

        # ── 左右分栏 ──
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("searchSplitter")
        self.splitter.setHandleWidth(2)

        # 左侧：产品列表
        self.product_list = ProductList(self._cfg.nas_root_path)
        self.product_list.product_selected.connect(self._on_product_selected)
        self.product_list.product_double_clicked.connect(self._open_folder)
        self.splitter.addWidget(self.product_list)

        # 右侧：产品工作台
        self.right_panel = RightPanel(self._db)
        self.right_panel.open_folder_requested.connect(self._open_folder)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([420, 780])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        layout.addWidget(self.splitter, 1)

    # ── 搜索 ──────────────────────────────────────────────────────
    def _on_search(self, query: str):
        if not query:
            self._on_clear()
            return
        results = self._db.search_products(query)

        # 为每个产品补充：主图路径、分类
        for r in results:
            # 从名称提取分类
            r["category"] = _extract_category(r.get("name", ""))
            # 主图路径
            main_path = self._db.get_product_main_image_path(r["product_id"])
            if main_path:
                nas_root = self._cfg.nas_root_path
                r["main_image_path"] = (
                    os.path.join(nas_root, main_path)
                    if nas_root and not os.path.isabs(main_path)
                    else main_path
                )
            else:
                r["main_image_path"] = ""

        self._current_products = results
        self.product_list.set_products(results)

        n = len(results)
        self.status_label.setText(f"搜索完成：{n} 个产品")

    def _on_clear(self):
        self._current_products = []
        self._current_product = None
        self.product_list.clear()
        self.right_panel.show_empty()
        self.status_label.setText("就绪")

    # ── 产品选中 ──────────────────────────────────────────────────
    def _on_product_selected(self, product: dict):
        self._current_product = product
        product_id = product["product_id"]

        images = self._db.get_images_for_product(product_id)
        self.right_panel.set_product(product, images, self._cfg.nas_root_path)

    def _open_folder(self, path: str):
        _safe_open_folder(path, self._cfg.nas_root_path)

    # ── 工具栏按钮事件（同原版）───────────────────────────────────
    def _on_import_products(self):
        dlg = ImportDialog(self._db, self)
        if dlg.exec() == ImportDialog.DialogCode.Accepted:
            self.status_changed.emit()

    def _on_incremental_scan(self):
        self._start_scan(incremental=True)

    def _on_full_scan(self):
        reply = QMessageBox.question(
            self, "确认重建索引",
            "将清空所有图片索引数据并重新扫描。\n"
            "现有的产品数据不受影响。\n\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._start_scan(incremental=False)

    def _on_open_settings(self):
        dlg = SettingsDialog(self._db, self._cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.status_changed.emit()
            self.product_list.set_nas_root(self._cfg.nas_root_path)

    def _start_scan(self, incremental: bool):
        if self._scan_thread is not None:
            try:
                if self._scan_thread.isRunning():
                    QMessageBox.information(self, "扫描进行中", "上一次扫描尚未完成。")
                    return
            except RuntimeError:
                pass
        self._scan_thread = None
        self._scan_worker = None

        root = self._cfg.nas_root_path
        if not root:
            QMessageBox.information(self, "未配置 NAS 路径",
                "请点击 ⚙️ 设置图片根目录后再扫描。")
            return
        if not os.path.exists(root):
            QMessageBox.critical(self, "路径不存在",
                f"图片根目录不存在：\n{root}")
            return

        if not incremental:
            self._db.clear_index()

        self._set_buttons_enabled(False)
        self.status_label.setText("扫描中…")

        last_scan = self._cfg.last_scan_time if incremental else 0.0
        self._scan_worker = ScanWorker(self._db, root,
            incremental=incremental, last_scan_time=last_scan)
        self._scan_thread = ScanThread(self._scan_worker)

        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.status_message.connect(self._on_scan_status)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.start()

    def _on_scan_progress(self, current: int, total: int):
        self.status_label.setText(f"扫描中… {current}/{total}")

    def _on_scan_status(self, msg: str):
        self.status_label.setText(msg)

    def _on_scan_finished(self, stats: dict):
        self._set_buttons_enabled(True)
        import time
        self._cfg.last_scan_time = time.time()
        files = stats.get("files", 0)
        folders = stats.get("folders", 0)
        linked = stats.get("linked", 0)
        self.status_label.setText(
            f"扫描完成：{files} 张图, {folders} 个文件夹, {linked} 组关联")
        self.status_changed.emit()

    def _on_scan_error(self, msg: str):
        self._set_buttons_enabled(True)
        self.status_label.setText(f"错误: {msg}")
        QMessageBox.critical(self, "扫描失败", msg)

    def _set_buttons_enabled(self, enabled: bool):
        # 遍历工具栏中的按钮
        toolbar = self.findChild(QWidget, "searchToolbar")
        if toolbar:
            for btn in toolbar.findChildren(QPushButton):
                btn.setEnabled(enabled)

    def refresh_status(self):
        image_count = self._db.get_image_count()
        product_count = self._db.get_product_count()
        if image_count > 0:
            folder_count = self._db.get_folder_count()
            self.status_label.setText(
                f"{image_count} 张图, {folder_count} 个文件夹")
        elif product_count > 0:
            self.status_label.setText(f"就绪 ({product_count} 个产品)")
        else:
            self.status_label.setText("就绪 — 请导入产品或扫描目录")
