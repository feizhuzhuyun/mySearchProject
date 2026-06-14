"""
本地电子产品图片智能检索工具
Phase 0: 基础框架 — 主窗口、标签页、系统托盘

基于 PySide6，无边框窗口 + 原生边缘拖拽缩放 + 现代暗色主题。
"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    Qt, QRect, QPoint, QAbstractNativeEventFilter, QThread, Signal,
)
from PySide6.QtGui import (
    QIcon, QAction, QMouseEvent, QShortcut,
    QPainter, QColor, QFont, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import Config
from database import Database
from theme import (
    ThemeColors, THEME_DARK, THEME_LIGHT,
    ThemeManager, ThemeWatcher, theme_manager,
    build_global_stylesheet,
)
from widgets import TitleBar, Card, Placeholder
from settings_dialog import SettingsDialog
from search_tab import SearchTab

# ---------------------------------------------------------------------------
# 应用常量
# ---------------------------------------------------------------------------
APP_NAME = "元器件图片检索"
APP_VERSION = "0.0.1"
WINDOW_WIDTH = 500
WINDOW_HEIGHT = 640
WINDOW_MIN_WIDTH = 340
WINDOW_MIN_HEIGHT = 420
TITLE_BAR_HEIGHT = 38
RESIZE_MARGIN = 6  # 边缘拖拽缩放敏感区宽度


# (theme system → theme.py)
# ==================================================================
# 原生边缘拖拽缩放 — Windows WM_NCHITTEST
# ==================================================================
def _is_win11_or_later() -> bool:
    """检查是否 Win11+（用于调整 resize 行为）。"""
    import platform
    ver = platform.version()
    try:
        build = int(ver.split(".")[-1])
        return build >= 22000
    except (ValueError, IndexError):
        return False


class ResizableWindow(QMainWindow):
    """
    无边框窗口基类：用 Windows WM_NCHITTEST 实现原生边缘拖拽缩放。

    子类需要：
      - centralWidget() 的 layout 有边缘留白 (RESIZE_MARGIN)
      - 调用 self._init_resize()
    """

    def _init_resize(self):
        """在子类 _setup_window 最后调用。"""
        self._resize_margin = RESIZE_MARGIN
        self._win11 = _is_win11_or_later()

    def nativeEvent(self, event_type, message):
        """拦截 Windows 原生的非客户区命中测试。"""
        import ctypes
        from ctypes import wintypes

        if sys.platform != "win32":
            return False, 0

        msg = ctypes.cast(
            ctypes.c_void_p(int(message)), ctypes.POINTER(wintypes.MSG)
        ).contents
        if msg.message != 0x0084:  # WM_NCHITTEST
            return False, 0

        # 从 lParam 取屏幕坐标（WM_NCHITTEST 是 SendMessage，坐标在 lParam）
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value

        # 转为窗口客户区坐标
        pt = self.mapFromGlobal(QPoint(x, y))
        px = pt.x()
        py = pt.y()

        m = self._resize_margin
        w = self.width()
        h = self.height()

        # 鼠标远离窗口时不做边缘判断（避免误触发 resize 死循环）
        if px < -m or px > w + m or py < -m or py > h + m:
            return False, 0

        on_left = px < m
        on_right = px > w - m
        on_top = py < m
        on_bottom = py > h - m

        # Win11 上用更小的顶角触发区（避免误触）
        corner_margin = m + 4

        # ── 角落 ──
        if on_top and on_left and py < corner_margin:
            return True, 13  # HTTOPLEFT
        if on_top and on_right and py < corner_margin:
            return True, 14  # HTTOPRIGHT
        if on_bottom and on_left and py > h - corner_margin:
            return True, 16  # HTBOTTOMLEFT
        if on_bottom and on_right and py > h - corner_margin:
            return True, 17  # HTBOTTOMRIGHT

        # ── 边缘 ──
        if on_left:
            return True, 10   # HTLEFT
        if on_right:
            return True, 11   # HTRIGHT
        if on_top:
            return True, 12   # HTTOP
        if on_bottom:
            return True, 15   # HTBOTTOM

        return False, 0



# ==================================================================
# AI 助手标签页
# ==================================================================
class AITab(QWidget):
    """🤖 AI 助手 — 截图 + OCR + 指令 + AI 回复。"""

    send_request = Signal(str, str)  # (ocr_text, user_instruction) — 后续阶段接入

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ── 截图区域 ──
        screenshot_frame = Card(padding=0)
        screenshot_frame.setMinimumHeight(140)
        self.screenshot_placeholder = Placeholder(
            "📸", "截图区域", "按 Ctrl+Shift+Z 截屏\n或拖入截图文件"
        )
        screenshot_frame.content.addWidget(self.screenshot_placeholder)
        layout.addWidget(screenshot_frame, 2)

        # ── OCR 文字 ──
        section_header("📝 OCR 识别文字", layout)
        self.ocr_text = QTextEdit()
        self.ocr_text.setReadOnly(True)
        self.ocr_text.setMaximumHeight(80)
        self.ocr_text.setPlaceholderText("截图后将在此显示识别到的文字…")
        layout.addWidget(self.ocr_text)

        # ── 指令输入行 ──
        section_header("💬 指令", layout)
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(8)

        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("如：帮我回复、总结要点、翻译…")
        self.cmd_input.setFixedHeight(36)
        self.cmd_input.returnPressed.connect(self._on_send)
        cmd_row.addWidget(self.cmd_input)

        self.btn_send = QPushButton("发送 →")
        self.btn_send.setObjectName("sendButton")
        self.btn_send.setFixedSize(72, 36)
        self.btn_send.clicked.connect(self._on_send)
        cmd_row.addWidget(self.btn_send)
        layout.addLayout(cmd_row)

        # ── AI 回复 ──
        section_header("🤖 AI 回复", layout)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("AI 回复将显示在此处，并自动复制到剪贴板…")
        layout.addWidget(self.result_text, 3)

    def _on_send(self):
        """占位：后续阶段接入 DeepSeek API。"""
        self.result_text.setPlainText("[阶段 5] DeepSeek API 尚未接入。")


def section_header(text: str, parent_layout: QVBoxLayout):
    """带柔和小标签的段落标题。"""
    label = QLabel(text)
    label.setProperty("sectionHeader", "yes")
    parent_layout.addWidget(label)



# ==================================================================
# 系统托盘
# ==================================================================
class SystemTray(QSystemTrayIcon):
    """系统托盘图标与右键菜单。"""

    def __init__(self, parent: QMainWindow):
        super().__init__(parent)
        self._parent = parent
        self.setIcon(self._make_icon(theme_manager.current))
        self.setToolTip(f"{APP_NAME} v{APP_VERSION}")

        menu = QMenu()

        show_action = QAction("📂 显示窗口")
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        menu.addSeparator()

        about_action = QAction(f"关于 {APP_NAME}")
        about_action.triggered.connect(
            lambda: self.showMessage(
                APP_NAME,
                f"版本 {APP_VERSION}\n本地电子产品图片智能检索工具",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        )
        menu.addAction(about_action)

        menu.addSeparator()

        quit_action = QAction("退出")
        quit_action.triggered.connect(parent.close_app)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        # 监听主题变更 → 重绘托盘图标
        theme_manager.theme_changed.connect(self._on_tray_theme_changed)

    def _show_window(self):
        self._parent.show()
        self._parent.raise_()
        self._parent.activateWindow()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    @staticmethod
    def _make_icon(theme: ThemeColors) -> QIcon:
        """绘制 32×32 托盘图标（跟随主题色）。"""
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)

        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 圆形背景 + 轻微光晕
        p.setBrush(QColor(theme.bg_menu))
        p.setPen(QPen(QColor(theme.accent), 2))
        p.drawEllipse(3, 3, 26, 26)

        # 填充
        p.setBrush(QColor(theme.accent))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(5, 5, 22, 22)

        # 🔍 emoji
        p.setPen(QColor(theme.bg_deepest))
        font = QFont("Segoe UI Emoji", 13)
        p.setFont(font)
        p.drawText(QRect(5, 5, 22, 22), Qt.AlignmentFlag.AlignCenter, "🔍")

        p.end()
        return QIcon(pix)

    def _on_tray_theme_changed(self, theme: ThemeColors):
        """系统主题变更时重绘托盘图标。"""
        self.setIcon(self._make_icon(theme))



# ==================================================================
# 主窗口
# ==================================================================
class MainWindow(ResizableWindow):
    """应用主窗口 — 无边框 + 原生缩放 + 标签页 + 系统托盘。"""

    def __init__(self, database: Database, config: Config):
        super().__init__()
        self._db = database
        self._cfg = config
        self._setup_window()
        self._setup_ui()
        self._apply_theme()
        self._setup_tray()
        self._init_resize()
        self._update_status_bar()
        # 监听系统主题变更
        theme_manager.theme_changed.connect(self._on_theme_changed)
        # 调试快捷键：Ctrl+Shift+T 强制切换主题
        self._debug_shortcut = QShortcut("Ctrl+Shift+T", self)
        self._debug_shortcut.activated.connect(self._debug_toggle_theme)

    def _setup_window(self):
        self.setWindowTitle(APP_NAME)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        # 无边框 + 置顶
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        # 居中
        screen = QApplication.primaryScreen()
        if screen:
            center = screen.geometry().center()
            self.move(
                center.x() - WINDOW_WIDTH // 2,
                center.y() - WINDOW_HEIGHT // 2,
            )

    def _apply_theme(self):
        """重建并应用当前主题的全局样式表。"""
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_global_stylesheet(theme_manager.current))

    def _on_theme_changed(self, _theme: ThemeColors):
        self._apply_theme()

    def _debug_toggle_theme(self):
        """Dev-only: 强制切换主题（不改变系统设置）。"""
        if theme_manager.current == THEME_DARK:
            theme_manager._current = THEME_LIGHT
        else:
            theme_manager._current = THEME_DARK
        theme_manager.theme_changed.emit(theme_manager.current)

    def _update_status_bar(self):
        """从数据库刷新状态栏计数与 NAS 路径。"""
        image_count = self._db.get_image_count()
        product_count = self._db.get_product_count()
        link_count = self._db.get_link_count()
        parts = []
        if image_count > 0:
            folder_count = self._db.get_folder_count()
            parts.append(f"索引：{image_count} 张图片, {folder_count} 个文件夹")
        else:
            parts.append("索引：0 张图片")
        if product_count > 0:
            parts.append(f"产品：{product_count} 个")
        if link_count > 0:
            parts.append(f"关联：{link_count} 组")
        self.status_index.setText(" | ".join(parts))

        # NAS 路径（显示第一个，过多时缩略 + 数量）
        paths = self._cfg.nas_root_paths
        if paths:
            label = paths[0]
            if len(label) > 28:
                label = "…" + label[-27:]
            if len(paths) > 1:
                label += f"  +{len(paths)-1}"
            self.status_path.setText(f"📁 {label}")
        else:
            self.status_path.setText("📁 未配置")

        self.status_hint.setText("就绪")
        # 同步刷新检索页内部状态
        self.search_tab.refresh_status()

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(
            RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN
        )
        outer.setSpacing(0)

        # ── 内容容器（圆角 + 阴影感） ──
        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 标题栏
        self.title_bar = TitleBar(self)
        content_layout.addWidget(self.title_bar)

        # 标签页
        self.tab_widget = QTabWidget()
        self.search_tab = SearchTab(self._db, self._cfg)
        self.search_tab.status_changed.connect(self._update_status_bar)
        self.ai_tab = AITab()
        self.tab_widget.addTab(self.search_tab, "📦  图片检索")
        self.tab_widget.addTab(self.ai_tab, "🤖  AI 助手")
        content_layout.addWidget(self.tab_widget, 1)

        # 状态栏
        status = QWidget()
        status.setObjectName("statusBar")
        status.setFixedHeight(22)
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(10, 0, 10, 0)
        status_layout.setSpacing(12)

        self.status_index = QLabel("索引：0 张图片")
        self.status_index.setObjectName("statusIndex")
        status_layout.addWidget(self.status_index)

        status_layout.addStretch()

        self.status_path = QLabel("")
        self.status_path.setObjectName("statusHint")
        status_layout.addWidget(self.status_path)

        self.status_hint = QLabel("就绪")
        self.status_hint.setObjectName("statusHint")
        status_layout.addWidget(self.status_hint)

        content_layout.addWidget(status)
        outer.addWidget(content)

    def _setup_tray(self):
        self.tray = SystemTray(self)
        self.tray.show()

    def close_app(self):
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage(
            APP_NAME,
            "已最小化到系统托盘，双击图标恢复。",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )



# ==================================================================
# 入口
# ==================================================================
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    # 初始化数据层
    cfg = Config()
    database = Database(cfg.db_path)
    database.init_db()

    # 安装系统主题变更监听
    watcher = ThemeWatcher(theme_manager)
    app.installNativeEventFilter(watcher)

    window = MainWindow(database, cfg)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
