"""主题系统。"""
import sys
from string import Template
from PySide6.QtCore import QObject, Signal, QAbstractNativeEventFilter

class ThemeColors:
    """语义化颜色令牌 — 暗色/亮色两套调色板。"""

    __slots__ = (
        "bg_deepest", "bg_menu", "bg_surface", "bg_input",
        "bg_button", "bg_button_hover", "bg_input_focus",
        "text_subtle", "text_header", "text_secondary", "text_primary",
        "accent", "accent_hover", "accent_pressed", "danger",
        "border_default", "border_focus",
    )

    def __init__(
        self, *, bg_deepest, bg_menu, bg_surface, bg_input,
        bg_button, bg_button_hover, bg_input_focus,
        text_subtle, text_header, text_secondary, text_primary,
        accent, accent_hover, accent_pressed, danger,
        border_default, border_focus,
    ):
        self.bg_deepest = bg_deepest
        self.bg_menu = bg_menu
        self.bg_surface = bg_surface
        self.bg_input = bg_input
        self.bg_button = bg_button
        self.bg_button_hover = bg_button_hover
        self.bg_input_focus = bg_input_focus
        self.text_subtle = text_subtle
        self.text_header = text_header
        self.text_secondary = text_secondary
        self.text_primary = text_primary
        self.accent = accent
        self.accent_hover = accent_hover
        self.accent_pressed = accent_pressed
        self.danger = danger
        self.border_default = border_default
        self.border_focus = border_focus

    def __eq__(self, other):
        if not isinstance(other, ThemeColors):
            return NotImplemented
        return all(
            getattr(self, s) == getattr(other, s)
            for s in self.__slots__
        )

    def as_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}


# ── Catppuccin Mocha (暗色) ──
THEME_DARK = ThemeColors(
    bg_deepest="#11111b", bg_menu="#1e1e2e", bg_surface="#181825",
    bg_input="#313244", bg_button="#45475a", bg_button_hover="#585b70",
    bg_input_focus="#363854",
    text_subtle="#6c7086", text_header="#a6adc8", text_secondary="#bac2de",
    text_primary="#cdd6f4",
    accent="#89b4fa", accent_hover="#b4befe", accent_pressed="#74c7ec",
    danger="#f38ba8",
    border_default="#313244", border_focus="#89b4fa",
)

# ── Catppuccin Latte (亮色) ──
THEME_LIGHT = ThemeColors(
    bg_deepest="#dce0e8", bg_menu="#e6e9ef", bg_surface="#eff1f5",
    bg_input="#ccd0da", bg_button="#bcc0cc", bg_button_hover="#acb0be",
    bg_input_focus="#e6e9ef",
    text_subtle="#9ca0b0", text_header="#7c7f93", text_secondary="#5c5f77",
    text_primary="#4c4f69",
    accent="#1e66f5", accent_hover="#7287fd", accent_pressed="#04a5e5",
    danger="#d20f39",
    border_default="#ccd0da", border_focus="#1e66f5",
)


# ── 主题管理器 ──
class ThemeManager(QObject):
    """检测 Windows 系统主题并通知变更。"""

    theme_changed = Signal(ThemeColors)

    def __init__(self):
        super().__init__()
        self._current: ThemeColors | None = None

    @property
    def current(self) -> ThemeColors:
        if self._current is None:
            self._current = self._detect_system_theme()
        return self._current

    @staticmethod
    def _detect_system_theme() -> ThemeColors:
        """读取 Windows 注册表 AppsUseLightTheme 值。"""
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return THEME_LIGHT if value else THEME_DARK
        except OSError:
            return THEME_DARK

    def refresh(self):
        new_theme = self._detect_system_theme()
        if new_theme != self._current:
            self._current = new_theme
            self.theme_changed.emit(new_theme)


theme_manager = ThemeManager()


# ── 系统主题变更监听 ──
class ThemeWatcher(QAbstractNativeEventFilter):
    """监听 WM_SETTINGCHANGE → 系统主题切换。"""

    def __init__(self, mgr: ThemeManager):
        super().__init__()
        self._mgr = mgr

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0
        import ctypes
        from ctypes import wintypes
        msg = ctypes.cast(
            ctypes.c_void_p(int(message)), ctypes.POINTER(wintypes.MSG)
        ).contents
        if msg.message == 0x001A and msg.lParam:  # WM_SETTINGCHANGE
            try:
                lparam_str = ctypes.c_wchar_p(msg.lParam).value
                if lparam_str == "ImmersiveColorSet":
                    self._mgr.refresh()
            except Exception:
                pass
        return False, 0

_STYLE_TEMPLATE = Template("""
/* === 基础 === */
QMainWindow {
    background-color: $bg_deepest;
}
QWidget {
    color: $text_primary;
    font-family: "Microsoft YaHei UI", "Segoe UI", "Noto Sans SC", sans-serif;
    font-size: 13px;
}

/* === 标签页 === */
QTabWidget::pane {
    border: none;
    background-color: $bg_deepest;
    padding: 0;
}
QTabBar {
    background-color: $bg_surface;
    border-bottom: 1px solid $border_default;
    padding-left: 4px;
}
QTabBar::tab {
    background: transparent;
    color: $text_subtle;
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    font-size: 12.5px;
}
QTabBar::tab:selected {
    color: $text_primary;
    border-bottom: 2px solid $accent;
    background-color: $bg_deepest;
}
QTabBar::tab:hover:!selected {
    color: $text_secondary;
}

/* === 按钮 === */
QPushButton {
    background: $bg_button;
    border: 1px solid $bg_button_hover;
    border-radius: 5px;
    padding: 5px 12px;
    color: $text_primary;
    font-size: 12.5px;
}
QPushButton:hover {
    background: $bg_button_hover;
    border-color: $text_subtle;
}
QPushButton:pressed {
    background: $bg_input;
}

/* === 搜索框 === */
QLineEdit {
    background-color: $bg_input;
    border: 1.5px solid $bg_button;
    border-radius: 8px;
    padding: 8px 12px;
    color: $text_primary;
    font-size: 13px;
    selection-background-color: $accent;
    selection-color: $bg_deepest;
}
QLineEdit:focus {
    border-color: $accent;
    background-color: $bg_input_focus;
}
QLineEdit::placeholder {
    color: $bg_button_hover;
}

/* === 多行文本框 === */
QTextEdit {
    background-color: $bg_input;
    border: 1.5px solid $bg_button;
    border-radius: 6px;
    padding: 8px 10px;
    color: $text_primary;
    font-size: 12.5px;
    selection-background-color: $accent;
    selection-color: $bg_deepest;
}
QTextEdit:focus {
    border-color: $accent;
}

/* === 滚动条 === */
QScrollBar:vertical {
    background: $bg_deepest;
    width: 6px;
    margin: 0;
    border: none;
}
QScrollBar::handle:vertical {
    background: $bg_button;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: $bg_button_hover;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: $bg_deepest;
    height: 6px;
    margin: 0;
    border: none;
}
QScrollBar::handle:horizontal {
    background: $bg_button;
    border-radius: 3px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: $bg_button_hover;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* === 分割器 === */
QSplitter::handle {
    background-color: $border_default;
    margin: 2px 0;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}

/* === 工具提示 === */
QToolTip {
    background-color: $bg_input;
    color: $text_primary;
    border: 1px solid $bg_button;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

/* === 菜单 === */
QMenu {
    background-color: $bg_menu;
    border: 1px solid $bg_button;
    border-radius: 6px;
    padding: 4px 0;
}
QMenu::item {
    padding: 6px 28px 6px 14px;
    color: $text_primary;
}
QMenu::item:selected {
    background-color: $bg_button;
}
QMenu::separator {
    height: 1px;
    background: $border_default;
    margin: 4px 8px;
}

/* === 标题栏 === */
#titleBar {
    background-color: $bg_surface;
    border-bottom: 1px solid $border_default;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
#titleBar QLabel {
    color: $text_primary;
    font-size: 12px;
    font-weight: 600;
}
#titleBar QPushButton {
    background: transparent;
    border: none;
    color: $text_subtle;
    font-size: 13px;
    padding: 0;
    min-width: 30px;
    min-height: 30px;
    border-radius: 4px;
}
#titleBar QPushButton:hover {
    background: $bg_input;
    color: $text_primary;
}
#titleBar QPushButton#btnClose:hover {
    background: $danger;
    color: $bg_deepest;
}
#titleBar QPushButton#btnPin {
    font-size: 13px;
}
#titleBar QPushButton#btnPin:checked {
    color: $accent;
}
#versionLabel {
    color: $bg_button_hover;
    font-weight: normal;
    font-size: 10px;
}

/* === 卡片 === */
#card {
    background-color: $bg_surface;
    border: 1px solid $border_default;
    border-radius: 8px;
}

/* === 占位符 === */
QLabel[placeholderRole="icon"] {
    font-size: 36px;
    color: $bg_button;
}
QLabel[placeholderRole="title"] {
    font-size: 13px;
    color: $text_subtle;
    font-weight: 600;
}
QLabel[placeholderRole="desc"] {
    font-size: 11px;
    color: $bg_button_hover;
}

/* === 内容容器 === */
#content {
    background-color: $bg_deepest;
    border: 1px solid $border_default;
    border-radius: 8px;
}

/* === 状态栏 === */
#statusBar {
    background-color: $bg_surface;
    border-top: 1px solid $border_default;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}
#statusIndex, #statusHint {
    color: $bg_button_hover;
    font-size: 10px;
}

/* === 检索页搜索容器 === */
#searchContainer {
    background-color: $bg_surface;
}
#searchInput {
    background-color: $bg_input;
    border: 2px solid $bg_button;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 13px;
}
#searchInput:focus {
    border-color: $accent;
    background-color: $bg_input_focus;
}

/* === 检索页工具栏 === */
#searchToolbar {
    background-color: $bg_surface;
    border-bottom: 1px solid $border_default;
}
QPushButton[toolbarButton="yes"] {
    background: $bg_input;
    border: 1px solid $bg_button;
    border-radius: 5px;
    padding: 4px 10px;
    font-size: 11.5px;
}
QPushButton[toolbarButton="yes"]:hover {
    background: $bg_button;
}
#searchStatusLabel {
    color: $bg_button_hover;
    font-size: 11px;
}
#searchSplitter::handle {
    background-color: $border_default;
    margin: 8px 0;
    border-radius: 1px;
}

/* === 发送按钮 === */
#sendButton {
    background-color: $accent;
    color: $bg_deepest;
    border: none;
    font-weight: 600;
}
#sendButton:hover {
    background-color: $accent_hover;
}
#sendButton:pressed {
    background-color: $accent_pressed;
}

/* === 搜索结果列表 === */
#searchResultList {
    background-color: $bg_deepest;
    border: none;
    outline: none;
    font-size: 12.5px;
    padding: 2px;
}
#searchResultList::item {
    padding: 8px 10px;
    border-bottom: 1px solid $border_default;
    color: $text_primary;
}
#searchResultList::item:selected {
    background-color: $bg_input;
    color: $accent;
}
#searchResultList::item:hover:!selected {
    background-color: $bg_surface;
}
#itemFieldLabel {
    color: $text_primary;
    font-size: 12px;
}
#itemSubLabel {
    color: $text_subtle;
    font-size: 11px;
}
#copyBtn {
    border-radius: 3px;
}
#copyBtn:hover {
    background-color: $bg_button;
}

/* === 缩略图区域 === */
#thumbScroll {
    background-color: $bg_deepest;
    border: none;
}
#thumbItem {
    background: transparent;
}
#thumbImage {
    border: 1px solid $border_default;
    border-radius: 4px;
}
#thumbFileName {
    color: $text_subtle;
    font-size: 10px;
}

/* === 设置对话框 === */
#settingsDbPath, #settingsStats {
    color: $text_subtle;
    font-size: 12px;
}
#settingsSep {
    background: $border_default;
    max-height: 1px;
}

/* === 路径条 === */
#pathBar {
    background-color: $bg_input;
    color: $accent;
    font-size: 12px;
    padding: 6px 12px;
    border-bottom: 1px solid $border_default;
    min-height: 26px;
}

/* === 段落标题 === */
QLabel[sectionHeader="yes"] {
    color: $text_header;
    font-size: 11.5px;
    font-weight: 600;
    padding: 0;
}
""")


def build_global_stylesheet(theme: ThemeColors) -> str:
    """用主题色填充样式模板。"""
    return _STYLE_TEMPLATE.substitute(theme.as_dict())

