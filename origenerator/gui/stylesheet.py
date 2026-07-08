from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BG_BUTTON,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BORDER_SUBTLE, BORDER_PANEL, BLUE,
)


def _h(color) -> str:
    return color.name()


def build_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {_h(BG_PRIMARY)};
        color: {_h(TEXT_PRIMARY)};
    }}
    QLabel {{
        color: {_h(TEXT_SECONDARY)};
    }}
    QLabel#estimateLabel {{
        color: {_h(TEXT_MUTED)};
    }}
    QToolTip {{
        /* QToolTip is a QWidget, so the global QWidget rule above paints it but
           leaves it borderless and hard to read; style it explicitly so the
           toolbar buttons' tooltips actually show, legibly, on hover. */
        background-color: {_h(BG_TERTIARY)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 3px;
        padding: 4px 6px;
    }}
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 3px;
        padding: 4px;
    }}
    QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {_h(BLUE)};
    }}
    QComboBox {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 3px;
        padding: 4px 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {_h(BG_TERTIARY)};
        color: {_h(TEXT_PRIMARY)};
        selection-background-color: {_h(BLUE)};
    }}
    QPushButton {{
        background-color: {_h(BG_BUTTON)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 4px;
        padding: 6px 16px;
    }}
    QPushButton:hover {{
        background-color: {_h(BG_TERTIARY)};
    }}
    QPushButton:pressed {{
        background-color: {_h(BLUE)};
    }}
    QPushButton:disabled {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_MUTED)};
        border: 1px solid {_h(BORDER_SUBTLE)};
    }}
    /* Generate is set apart by colour and weight only, not size, so it sits the
       same height as the other buttons in its row (Go-to-folder, Send-to-Evolver,
       Cancel) — one consistent button size, not a taller primary. */
    QPushButton#generateBtn {{
        background-color: {_h(BLUE)};
        font-weight: bold;
    }}
    /* While a run is in flight Generate greys out beside the active Cancel; the id
       selector above out-specifies the base :disabled rule, so restate it here. */
    QPushButton#generateBtn:disabled {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_MUTED)};
    }}
    QToolButton {{
        background-color: {_h(BG_BUTTON)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 4px;
        padding: 2px 10px;
        font-weight: bold;
    }}
    QToolButton:hover {{
        background-color: {_h(BG_TERTIARY)};
    }}
    QToolButton#iconButton {{
        padding: 4px;
    }}
    QToolButton:disabled {{
        background-color: {_h(BG_SECONDARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
    }}
    QProgressBar {{
        background-color: {_h(BG_SECONDARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 3px;
        text-align: center;
        color: {_h(TEXT_PRIMARY)};
    }}
    QProgressBar::chunk {{
        background-color: {_h(BLUE)};
    }}
    QScrollArea {{
        border: none;
    }}
    QSplitter::handle {{
        background-color: {_h(BG_SECONDARY)};
    }}
    QSplitter::handle:hover {{
        background-color: {_h(BLUE)};
    }}
    QGroupBox {{
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_PANEL)};
        border-radius: 4px;
        margin-top: 12px;
        padding-top: 16px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }}
    QTabBar::tab {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_MUTED)};
        padding: 8px 20px;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {_h(TEXT_PRIMARY)};
        border-bottom: 2px solid {_h(BLUE)};
    }}
    QTabBar::tab:hover {{
        color: {_h(TEXT_PRIMARY)};
    }}
    QLabel#combineHeading {{
        color: {_h(TEXT_MUTED)};
        font-weight: bold;
        padding: 2px 0;
    }}
    QLabel#dropSlot {{
        border: 1px dashed {_h(BORDER_PANEL)};
        border-radius: 4px;
        color: {_h(TEXT_MUTED)};
        padding: 8px;
    }}
    QLabel#dropSlot[dragActive="true"] {{
        border: 1px solid {_h(BLUE)};
        background-color: {_h(BG_TERTIARY)};
        color: {_h(TEXT_PRIMARY)};
    }}
    """
