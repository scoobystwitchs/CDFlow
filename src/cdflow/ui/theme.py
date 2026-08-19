"""Central visual language for the CDFlow Qt interface.

The application deliberately keeps its styling in one module.  Pages should use
semantic object names/properties instead of embedding colours in widget code.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from cdflow.app.constants import DEFAULT_ACCENT


@dataclass(frozen=True, slots=True)
class Theme:
    background: str = "#090C11"
    sidebar: str = "#0C1016"
    panel: str = "#10151D"
    panel_alt: str = "#141A23"
    raised: str = "#181F29"
    border: str = "#242C37"
    border_soft: str = "#1B222C"
    text: str = "#F4F6FA"
    text_muted: str = "#929CAA"
    text_faint: str = "#626C79"
    accent: str = DEFAULT_ACCENT
    accent_hover: str = "#FF5797"
    accent_pressed: str = "#D92E70"
    success: str = "#35C58A"
    warning: str = "#F2B84B"
    danger: str = "#F05D6C"


DEFAULT_THEME = Theme()


def with_accent(accent: str) -> Theme:
    """Return a theme using *accent*, falling back when it is not a colour."""

    colour = QColor(accent)
    if not colour.isValid():
        return DEFAULT_THEME
    hover = colour.lighter(118).name()
    pressed = colour.darker(115).name()
    return Theme(accent=colour.name(), accent_hover=hover, accent_pressed=pressed)


def apply_theme(app: QApplication, accent: str = DEFAULT_ACCENT) -> Theme:
    """Install the dark palette and stylesheet on a QApplication."""

    theme = with_accent(accent)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.background))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.panel))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.panel_alt))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.raised))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.panel_alt))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.text_faint))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme.text_faint))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme.text_faint))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet(theme))
    app.setProperty("cdflowAccent", theme.accent)
    return theme


def build_stylesheet(t: Theme = DEFAULT_THEME) -> str:
    """Return the complete Qt stylesheet for the application."""

    accent = QColor(t.accent)
    accent_soft = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24)"
    accent_soft_hover = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34)"
    return f"""
    * {{
        color: {t.text};
        font-family: "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
        font-size: 13px;
        outline: none;
    }}
    QMainWindow, QWidget#appRoot, QWidget#pageRoot {{
        background: {t.background};
    }}
    QToolTip {{
        color: {t.text};
        background: {t.raised};
        border: 1px solid {t.border};
        padding: 5px 7px;
    }}
    QLabel#appName {{ font-weight: 700; font-size: 13px; }}
    QLabel#pageTitle {{ font-weight: 700; font-size: 24px; }}
    QLabel#albumTitle {{ font-weight: 700; font-size: 22px; }}
    QLabel#sectionTitle {{ font-weight: 650; font-size: 14px; }}
    QLabel#cardTitle {{ font-weight: 650; font-size: 13px; }}
    QLabel#muted, QLabel[muted="true"] {{ color: {t.text_muted}; }}
    QLabel#faint, QLabel[faint="true"] {{ color: {t.text_faint}; }}
    QLabel#accent, QLabel[accent="true"] {{ color: {t.accent}; }}
    QLabel#danger {{ color: {t.danger}; }}
    QLabel#emptyTitle {{ font-size: 20px; font-weight: 650; }}
    QLabel#emptyBody {{ color: {t.text_muted}; font-size: 13px; }}
    QFrame#sidebar {{
        background: {t.sidebar};
        border-right: 1px solid {t.border_soft};
    }}
    QFrame#card, QFrame[card="true"] {{
        background: {t.panel};
        border: 1px solid {t.border_soft};
        border-radius: 10px;
    }}
    QFrame#innerCard {{
        background: {t.panel_alt};
        border: 1px solid {t.border_soft};
        border-radius: 8px;
    }}
    QFrame#albumCard {{
        background: {t.panel};
        border: 1px solid {t.border_soft};
        border-radius: 10px;
    }}
    QFrame#albumCard:hover, QFrame#albumCard:focus {{
        background: {t.panel_alt};
        border-color: {t.accent};
    }}
    QFrame#separator {{ background: {t.border_soft}; border: none; }}
    QPushButton {{
        min-height: 30px;
        padding: 0 12px;
        background: {t.panel_alt};
        border: 1px solid {t.border};
        border-radius: 7px;
        font-weight: 550;
    }}
    QPushButton:hover {{ background: {t.raised}; border-color: #35404D; }}
    QPushButton:pressed {{ background: #0E131A; }}
    QPushButton:disabled {{ color: {t.text_faint}; background: #0F1319; border-color: {t.border_soft}; }}
    QPushButton#primaryButton {{
        color: white;
        background: {t.accent};
        border-color: {t.accent};
        font-weight: 650;
    }}
    QPushButton#primaryButton:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
    QPushButton#primaryButton:pressed {{ background: {t.accent_pressed}; }}
    QPushButton#dangerButton {{ color: {t.danger}; }}
    QPushButton#iconButton, QToolButton#iconButton {{
        padding: 0;
        min-width: 32px;
        min-height: 32px;
        max-width: 32px;
        max-height: 32px;
        background: transparent;
        border: none;
        border-radius: 16px;
    }}
    QPushButton#iconButton:hover, QToolButton#iconButton:hover {{ background: {t.raised}; }}
    QPushButton#iconButton:checked, QToolButton#iconButton:checked {{ background: {accent_soft_hover}; }}
    QPushButton#playButton {{
        min-width: 42px; max-width: 42px;
        min-height: 42px; max-height: 42px;
        padding: 0;
        color: white;
        background: {t.accent};
        border: none;
        border-radius: 21px;
    }}
    QPushButton#playButton:hover {{ background: {t.accent_hover}; }}
    QPushButton#navButton {{
        min-height: 36px;
        padding: 0 12px;
        text-align: left;
        font-weight: 500;
        background: transparent;
        border: none;
        border-radius: 7px;
        color: {t.text_muted};
    }}
    QPushButton#navButton:hover {{ color: {t.text}; background: {t.panel_alt}; }}
    QPushButton#navButton:checked {{ color: white; background: {accent_soft_hover}; }}
    QPushButton#driveButton {{
        min-height: 48px;
        text-align: left;
        padding: 6px 10px;
        color: {t.text_muted};
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
    }}
    QPushButton#driveButton:hover {{ background: {t.panel_alt}; }}
    QPushButton#driveButton:checked {{ color: {t.text}; background: {t.panel_alt}; border-color: {t.border}; }}
    QPushButton#accentSwatch {{
        min-width: 24px; max-width: 24px;
        min-height: 24px; max-height: 24px;
        padding: 0; border-radius: 12px;
    }}
    QLineEdit, QComboBox, QSpinBox {{
        min-height: 32px;
        padding: 0 9px;
        background: {t.panel_alt};
        border: 1px solid {t.border};
        border-radius: 6px;
        selection-background-color: {t.accent};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {t.accent}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{
        background: {t.raised};
        border: 1px solid {t.border};
        selection-background-color: {accent_soft_hover};
        padding: 4px;
    }}
    QCheckBox {{ spacing: 8px; color: {t.text}; }}
    QSlider::groove:horizontal {{ height: 3px; border-radius: 1px; background: #303844; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 1px; }}
    QSlider::handle:horizontal {{
        width: 12px; height: 12px; margin: -5px 0;
        border-radius: 6px; background: {t.accent};
    }}
    QSlider::handle:horizontal:hover {{ background: {t.accent_hover}; }}
    QProgressBar {{
        min-height: 7px; max-height: 7px;
        border: none; border-radius: 3px;
        background: #303844;
        text-align: center;
    }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}
    QTableView, QTreeView {{
        background: transparent;
        alternate-background-color: #0E131A;
        border: none;
        gridline-color: transparent;
        selection-background-color: {accent_soft};
        selection-color: white;
    }}
    QTableView::item, QTreeView::item {{
        min-height: 34px;
        padding: 0 8px;
        border-bottom: 1px solid {t.border_soft};
    }}
    QTableView::item:hover, QTreeView::item:hover {{ background: #171E27; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{
        min-height: 31px;
        padding: 0 8px;
        color: {t.text_muted};
        font-size: 10px;
        font-weight: 650;
        background: {t.panel_alt};
        border: none;
        border-bottom: 1px solid {t.border};
    }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #333D49; min-height: 30px; border-radius: 4px; }}
    QScrollBar::handle:vertical:hover {{ background: #465261; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: #333D49; min-width: 30px; border-radius: 4px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QTabWidget::pane {{ border: 1px solid {t.border_soft}; border-radius: 8px; background: {t.panel}; }}
    QTabBar::tab {{ min-height: 34px; padding: 0 15px; color: {t.text_muted}; background: transparent; }}
    QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}
    """


__all__ = ["DEFAULT_THEME", "Theme", "apply_theme", "build_stylesheet", "with_accent"]
