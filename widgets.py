"""可复用UI组件。"""
import os
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (QFrame,QHBoxLayout,QLabel,QMainWindow,QPushButton,QSizePolicy,QVBoxLayout,QWidget)

# Constants
TITLE_BAR_HEIGHT = 38
APP_NAME = "元器件图片检索"
APP_VERSION = "0.0.1"

class TitleBar(QFrame):
    """无边框窗口标题栏 — 拖拽移动 + 置顶/最小化/关闭。"""

    def __init__(self, parent: QMainWindow, title: str = APP_NAME):
        super().__init__(parent)
        self._parent = parent
        self._drag_pos: QPoint | None = None
        self._always_on_top = True  # 默认置顶

        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self.setObjectName("titleBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(2)

        # ── 图标 ──
        icon_label = QLabel("🔍")
        icon_label.setFixedWidth(22)
        icon_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(icon_label)

        # ── 标题 ──
        title_label = QLabel(title)
        title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(title_label)

        # ── 版本号 ──
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setObjectName("versionLabel")
        layout.addWidget(version_label)
        layout.addSpacing(8)

        # ── 置顶 ──
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setObjectName("btnPin")
        self.btn_pin.setToolTip("取消置顶" if self._always_on_top else "窗口置顶")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(True)
        self.btn_pin.clicked.connect(self._toggle_always_on_top)
        layout.addWidget(self.btn_pin)

        # ── 最小化 ──
        self.btn_min = QPushButton("─")
        self.btn_min.setToolTip("最小化到托盘")
        self.btn_min.setStyleSheet("font-weight: bold;")
        self.btn_min.clicked.connect(self._parent.hide)
        layout.addWidget(self.btn_min)

        # ── 关闭 ──
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("btnClose")
        self.btn_close.setToolTip("退出程序")
        self.btn_close.clicked.connect(self._parent.close_app)
        layout.addWidget(self.btn_close)

    def _toggle_always_on_top(self, checked: bool):
        self._always_on_top = checked
        flags = self._parent.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
            self.btn_pin.setToolTip("取消置顶")
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
            self.btn_pin.setToolTip("窗口置顶")
        self._parent.setWindowFlags(flags)
        self._parent.show()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self._parent.move(self._parent.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """双击标题栏切换最大化/还原（如果窗口支持调整大小）。"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._parent.isMaximized():
                self._parent.showNormal()
            else:
                self._parent.showMaximized()
        super().mouseDoubleClickEvent(event)

class Card(QFrame):
    """统一的圆角卡片容器。"""

    def __init__(self, parent=None, padding: int = 16):
        super().__init__(parent)
        self.setObjectName("card")
        self._padding = padding
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(8)

    @property
    def content(self) -> QVBoxLayout:
        """返回卡片的内容布局（避免覆盖 QWidget.layout）。"""
        return self._layout


class Placeholder(QWidget):
    """空状态占位组件 — 图标 + 标题 + 描述。"""

    def __init__(self, icon: str, title: str, desc: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setProperty("placeholderRole", "icon")
        layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setProperty("placeholderRole", "title")
        layout.addWidget(title_label)

        if desc:
            desc_label = QLabel(desc)
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_label.setProperty("placeholderRole", "desc")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

