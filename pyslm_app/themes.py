"""Colour themes of the desktop application."""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class Theme:
    name: str
    window: str            # window background
    panel: str             # side panels
    panel_border: str
    text: str
    muted: str             # secondary text, section titles
    input: str             # spin boxes, combo boxes, lists
    input_border: str
    button: str
    button_border: str
    button_hover: str
    primary: str           # main action (may be a qlineargradient)
    primary_hover: str
    primary_text: str
    accent: str            # progress, focus, slider handle
    badge: str             # "?" help badges
    badge_text: str
    log: str               # diagnostics area
    log_text: str
    viewer: Tuple[int, int, int]
    grid: Tuple[int, int, int, int]
    radius: int = 8
    style: str = "classic"  # "apple": pill buttons, sentence-case titles, segmented tabs


THEMES: Dict[str, Theme] = {
    "Notte": Theme(
        name="Notte", window="#13181f", panel="#1a2129", panel_border="#2a3541", text="#e6ebf0",
        muted="#9eacba", input="#10151b", input_border="#34404c", button="#28323e",
        button_border="#3a4654", button_hover="#344252", primary="#087f75", primary_hover="#0a9589",
        primary_text="#ffffff", accent="#2f8fd8", badge="#24384c", badge_text="#9fd0ff", log="#10151b",
        log_text="#aeb9c4", viewer=(211, 213, 215), grid=(160, 164, 168, 85), radius=8,
    ),
    "Aurora": Theme(
        name="Aurora", window="#eef2f8", panel="#ffffff", panel_border="#e1e6ef", text="#1c2433",
        muted="#6b7a90", input="#f5f7fb", input_border="#d7deea", button="#f2f4f9",
        button_border="#dde3ee", button_hover="#e6ebf5",
        primary="qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c5cff, stop:1 #3b82f6)",
        primary_hover="qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8f73ff, stop:1 #5294f8)",
        primary_text="#ffffff", accent="#6366f1", badge="#ece9ff", badge_text="#5b4bdb", log="#ffffff",
        log_text="#4a5568", viewer=(246, 248, 252), grid=(170, 178, 196, 70), radius=12,
    ),
    "Titanio": Theme(
        name="Titanio", window="#dfe2e6", panel="#f3f4f6", panel_border="#c9ced5", text="#1f242b",
        muted="#59636e", input="#ffffff", input_border="#b9c0c9", button="#e8eaee",
        button_border="#c3c8cf", button_hover="#dcdfe4", primary="#f26b1d", primary_hover="#ff7d33",
        primary_text="#ffffff", accent="#f26b1d", badge="#ffe7d8", badge_text="#c2500f", log="#f8f9fa",
        log_text="#3c4550", viewer=(214, 218, 223), grid=(130, 138, 148, 80), radius=4,
    ),
    "Laguna": Theme(
        name="Laguna", window="#e3eeee", panel="#f7fbfa", panel_border="#cfe0de", text="#163332",
        muted="#5b7c7a", input="#ffffff", input_border="#bcd6d3", button="#e9f3f2",
        button_border="#c6dcd9", button_hover="#dbecea",
        primary="qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f9b8e, stop:1 #14b8a6)",
        primary_hover="qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #12ad9f, stop:1 #2dd4bf)",
        primary_text="#ffffff", accent="#0f9b8e", badge="#d6f2ee", badge_text="#0b7d73", log="#fbfefd",
        log_text="#3d5a58", viewer=(236, 243, 243), grid=(140, 170, 168, 70), radius=10,
    ),
    "Ardesia": Theme(
        name="Ardesia", window="#2a323d", panel="#343e4b", panel_border="#45515f", text="#eef2f6",
        muted="#a9b6c4", input="#283039", input_border="#4d5a69", button="#3e4958",
        button_border="#526070", button_hover="#4a5768",
        primary="qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #38bdf8)",
        primary_hover="qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22b3f0, stop:1 #5ccafa)",
        primary_text="#0b1520", accent="#38bdf8", badge="#2b4a63", badge_text="#8fd8ff", log="#262d36",
        log_text="#c3cdd8", viewer=(222, 226, 231), grid=(150, 158, 168, 80), radius=10,
    ),
    "Cupertino": Theme(
        name="Cupertino", window="#f5f5f7", panel="#ffffff", panel_border="#e5e5ea", text="#1d1d1f",
        muted="#86868b", input="#ffffff", input_border="#d2d2d7", button="#ffffff",
        button_border="#d2d2d7", button_hover="#f2f2f4", primary="#0071e3", primary_hover="#0077ed",
        primary_text="#ffffff", accent="#0071e3", badge="#eef4fd", badge_text="#0071e3", log="#ffffff",
        log_text="#3a3a3c", viewer=(240, 240, 244), grid=(176, 176, 186, 60), radius=12, style="apple",
    ),
    "Cupertino Grigio": Theme(
        name="Cupertino Grigio", window="#d9d9de", panel="#ebebef", panel_border="#cdcdd3", text="#1d1d1f",
        muted="#6e6e73", input="#f7f7f9", input_border="#c3c3c9", button="#f7f7f9",
        button_border="#c3c3c9", button_hover="#dedee3", primary="#0071e3", primary_hover="#0077ed",
        primary_text="#ffffff", accent="#0071e3", badge="#dbe7f7", badge_text="#0062c4", log="#ebebef",
        log_text="#3a3a3c", viewer=(222, 222, 227), grid=(160, 160, 170, 70), radius=12, style="apple",
    ),
    "Cupertino Grafite": Theme(
        name="Cupertino Grafite", window="#3a3a3e", panel="#4a4a4f", panel_border="#5a5a60", text="#f2f2f7",
        muted="#aeaeb2", input="#3c3c41", input_border="#68686e", button="#5a5a60",
        button_border="#6a6a70", button_hover="#636369", primary="#0a84ff", primary_hover="#2b95ff",
        primary_text="#ffffff", accent="#0a84ff", badge="#2c4766", badge_text="#8cc4ff", log="#404045",
        log_text="#d1d1d6", viewer=(226, 226, 230), grid=(150, 150, 158, 80), radius=12, style="apple",
    ),
    "Cupertino Scuro": Theme(
        name="Cupertino Scuro", window="#1c1c1e", panel="#2c2c2e", panel_border="#3a3a3c", text="#f5f5f7",
        muted="#98989d", input="#1c1c1e", input_border="#48484a", button="#3a3a3c",
        button_border="#48484a", button_hover="#444446", primary="#0a84ff", primary_hover="#2b95ff",
        primary_text="#ffffff", accent="#0a84ff", badge="#1f3550", badge_text="#7cbcff", log="#242426",
        log_text="#c7c7cc", viewer=(214, 214, 219), grid=(150, 150, 158, 85), radius=12, style="apple",
    ),
}

DEFAULT_THEME = "Cupertino Grafite"


def stylesheet(theme: Theme) -> str:
    t = theme
    r = t.radius
    return f"""
    QMainWindow, QWidget {{ background: {t.window}; color: {t.text};
        font-family: "Segoe UI", "Segoe UI Variable Text", sans-serif; font-size: 9pt; }}
    QToolBar {{ background: {t.panel}; border: 0; border-bottom: 1px solid {t.panel_border};
        spacing: 8px; padding: 6px; }}
    QToolButton, QPushButton {{ background: {t.button}; color: {t.text}; border: 1px solid {t.button_border};
        border-radius: {max(r - 3, 3)}px; padding: 7px 12px; }}
    QToolButton:hover, QPushButton:hover {{ background: {t.button_hover}; }}
    QPushButton:disabled {{ color: {t.muted}; }}
    QPushButton#primaryButton {{ background: {t.primary}; color: {t.primary_text}; border: 0;
        font-weight: 600; padding: 9px 12px; }}
    QPushButton#primaryButton:hover {{ background: {t.primary_hover}; }}
    QFrame#sidePanel {{ background: {t.panel}; border: 1px solid {t.panel_border}; border-radius: {r}px; }}
    QFrame#sidePanel QLabel, QFrame#sidePanel QCheckBox, QWidget#titleRow {{ background: transparent; }}
    QScrollArea#sideScroll {{ background: transparent; border: 0; }}
    QToolButton#collapseHeader {{ background: {t.button}; color: {t.muted}; border: 1px solid {t.panel_border};
        border-radius: {max(r - 4, 3)}px; font-weight: 700; letter-spacing: 1px; text-align: left;
        padding: 6px 8px; }}
    QToolButton#collapseHeader:hover {{ background: {t.button_hover}; color: {t.text}; }}
    QToolButton#collapseHeader:checked {{ color: {t.text}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; border: 0; }}
    QScrollBar::handle:vertical {{ background: {t.input_border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.accent}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QLabel#helpBadge, QFrame#sidePanel QLabel#helpBadge {{ background: {t.badge}; color: {t.badge_text};
        border: 0; border-radius: 8px; font-size: 8pt; font-weight: 700; }}
    QLabel#helpBadge:hover, QFrame#sidePanel QLabel#helpBadge:hover {{ background: {t.accent}; color: #ffffff; }}
    QProgressBar {{ background: {t.input}; border: 1px solid {t.input_border}; border-radius: 6px;
        color: {t.text}; text-align: center; height: 16px; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 5px; }}
    QToolTip {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.input_border}; padding: 6px; }}
    QLabel#sectionTitle {{ color: {t.muted}; font-size: 8pt; font-weight: 700; letter-spacing: 1px;
        background: transparent; }}
    QLabel#valueLabel {{ color: {t.muted}; background: transparent; }}
    QDoubleSpinBox, QComboBox {{ background: {t.input}; color: {t.text}; border: 1px solid {t.input_border};
        border-radius: {max(r - 5, 3)}px; padding: 4px 6px; }}
    QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {t.accent}; }}
    QComboBox QAbstractItemView {{ background: {t.panel}; color: {t.text};
        selection-background-color: {t.accent}; selection-color: #ffffff; border: 1px solid {t.input_border}; }}
    QListWidget {{ background: {t.input}; color: {t.text}; border: 1px solid {t.input_border};
        border-radius: {max(r - 5, 3)}px; }}
    QListWidget::item:selected {{ background: {t.accent}; color: #ffffff; }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.input_border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {t.panel}; border: 2px solid {t.accent};
        width: 12px; margin: -6px 0; border-radius: 8px; }}
    QPlainTextEdit {{ background: {t.log}; border: 0; color: {t.log_text}; }}
    QTabWidget::pane {{ border: 0; }}
    QTabBar::tab {{ background: {t.button}; color: {t.muted}; padding: 5px 12px; border: 0;
        border-top-left-radius: 4px; border-top-right-radius: 4px; }}
    QTabBar::tab:selected {{ background: {t.log}; color: {t.text}; }}
    QDockWidget::title {{ background: {t.panel}; padding: 6px; }}
    QCheckBox {{ spacing: 8px; }}
    QStatusBar {{ background: {t.panel}; color: {t.muted}; border-top: 1px solid {t.panel_border}; }}
    """ + (_apple_overrides(t) if t.style == "apple" else "")


def _apple_overrides(t: Theme) -> str:
    """Extra rules for the Apple-like look, layered over the common stylesheet."""
    return f"""
    QToolBar {{ background: {t.window}; border: 0; padding: 8px 10px; spacing: 6px; }}
    QToolButton {{ background: transparent; border: 0; border-radius: 14px; padding: 6px 14px;
        color: {t.accent}; font-weight: 600; }}
    QToolButton:hover {{ background: {t.button_hover}; }}
    QPushButton {{ border-radius: 14px; padding: 6px 14px; }}
    QPushButton#primaryButton {{ border-radius: 14px; padding: 8px 14px; }}
    QFrame#sidePanel {{ border: 1px solid {t.panel_border}; border-radius: {t.radius}px; }}
    QLabel#sectionTitle {{ color: {t.text}; font-size: 10pt; font-weight: bold; letter-spacing: 0px; }}
    QToolButton#collapseHeader {{ background: transparent; border: 0; border-radius: 8px; color: {t.text};
        font-size: 10pt; font-weight: bold; letter-spacing: 0px;
        padding: 6px 4px; }}
    QToolButton#collapseHeader:hover {{ background: {t.button_hover}; }}
    QDoubleSpinBox, QComboBox {{ border-radius: 7px; padding: 4px 8px; }}
    QListWidget {{ border-radius: 8px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.input_border}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: #ffffff; border: 1px solid {t.input_border}; width: 18px;
        margin: -8px 0; border-radius: 10px; }}
    QScrollBar:vertical {{ width: 8px; }}
    QScrollBar::handle:vertical {{ background: {t.input_border}; border-radius: 4px; }}
    QTabBar::tab {{ background: {t.button_hover}; color: {t.text}; padding: 4px 16px; margin: 3px 0;
        border-radius: 0; }}
    QTabBar::tab:first {{ border-top-left-radius: 7px; border-bottom-left-radius: 7px; }}
    QTabBar::tab:last {{ border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
    QTabBar::tab:selected {{ background: {t.button}; border: 1px solid {t.input_border}; font-weight: 600; }}
    QDockWidget::title {{ background: {t.window}; color: {t.muted}; padding: 6px 10px; }}
    QPlainTextEdit {{ border: 1px solid {t.panel_border}; border-radius: 10px; padding: 4px; }}
    QStatusBar {{ background: {t.window}; border-top: 0; }}
    """
