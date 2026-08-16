from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BG_BUTTON, BG_KEYCAP,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BORDER_SUBTLE, BORDER_PANEL, BLUE,
)


def _h(color) -> str:
    return color.name()


def _spin_arrow_rules() -> str:
    """The step-button arrows, as ``image:`` rules over generated triangles.

    Qt takes an arrow only as a picture — the CSS zero-box-with-borders triangle
    draws a filled rectangle here, which is what appeared over the buttons — so
    :mod:`origenerator.gui.spin_arrows` renders one. If it can't, this contributes
    nothing and Qt draws its own arrow: uncertain color, but an arrow.
    """
    from origenerator.gui.spin_arrows import arrow_paths

    normal = arrow_paths(TEXT_PRIMARY)
    if normal is None:
        return ""
    muted = arrow_paths(TEXT_MUTED) or normal
    return f"""\
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: url("{normal[0]}");
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: url("{normal[1]}");
    }}
    QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{
        image: url("{muted[0]}");
    }}
    QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{
        image: url("{muted[1]}");
    }}"""


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
    QLabel#dimensionsHint {{
        color: {_h(TEXT_MUTED)};
    }}
    QToolTip {{
        /* Tooltips are top-level popups, so this rule only reaches them because
           the sheet is set on the QApplication (see app.main) — on a window it
           is inert, and the tooltips fall back to the native palette, which
           Windows 11's dark mode renders unreadably (light-on-light; the
           "missing" tooltips). Styled explicitly, and with square corners: a
           rounded stylesheet tooltip on Windows paints artifact boxes. */
        background-color: {_h(BG_TERTIARY)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        padding: 4px 6px;
    }}
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 3px;
        padding: 4px;
    }}
    QSpinBox, QDoubleSpinBox {{
        /* Room for the step buttons, so the value never runs under them. */
        padding-right: 18px;
    }}
    /* Styling a spin box at all hands Qt the whole widget, step buttons
       included — and the default it falls back to for them has no size, so the
       arrows render as dead slivers you cannot hit. Give them a real box and a
       drawn arrow and they work again. */
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border;
        width: 16px;
        background-color: {_h(BG_BUTTON)};
        border-left: 1px solid {_h(BORDER_SUBTLE)};
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-position: top right;
        border-top-right-radius: 3px;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-top: 1px solid {_h(BORDER_SUBTLE)};
        border-bottom-right-radius: 3px;
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
        background-color: {_h(BG_KEYCAP)};
    }}
    QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
    QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
        background-color: {_h(BLUE)};
    }}
{_spin_arrow_rules()}
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
    QComboBox QAbstractItemView::item:disabled {{
        /* The rule above colours every item, disabled ones included, so an
           unpickable entry would look exactly as pickable as the rest. Mute it. */
        color: {_h(TEXT_MUTED)};
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
    /* A collapsible param-form section header: a flat, full-width divider row,
       not a raised button. Left-aligned with its fold arrow, and it must not
       flash the primary blue on click the way the base :pressed rule would. */
    QPushButton#sectionHeader {{
        background-color: transparent;
        color: {_h(TEXT_PRIMARY)};
        border: none;
        border-bottom: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 0;
        text-align: left;
        font-weight: 600;
        padding: 4px 2px;
    }}
    QPushButton#sectionHeader:hover {{
        background-color: {_h(BG_SECONDARY)};
    }}
    QPushButton#sectionHeader:pressed {{
        background-color: {_h(BG_SECONDARY)};
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
    /* The derived-size padlock: a compact toggle floating between the width and
       height rows. It lights blue while unlocked (the fields are overridable). */
    QToolButton#dimensionUnlock {{
        padding: 2px 4px;
    }}
    QToolButton#dimensionUnlock:checked {{
        background-color: {_h(BLUE)};
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
        /* A hairline between tabs, so it reads which ✕ belongs to which. */
        border-right: 1px solid {_h(BORDER_SUBTLE)};
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {_h(TEXT_PRIMARY)};
        border-bottom: 2px solid {_h(BLUE)};
    }}
    QTabBar::tab:hover {{
        color: {_h(TEXT_PRIMARY)};
    }}
    /* The config pane's close-all and "+" stand in the tab row, right after the
       tabs, so they wear the tabs' own flat look rather than the raised, rounded,
       bordered QToolButton default — which read as a separate little toolbar
       bolted onto the strip. Same background, same muted text, same hover, and
       the transparent bottom rule that keeps them level with an unselected tab. */
    QToolButton#tabBarButton {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_MUTED)};
        border: none;
        border-right: 1px solid {_h(BORDER_SUBTLE)};
        border-bottom: 2px solid transparent;
        border-radius: 0;
        /* The tabs' own vertical padding, so a label and a tab's label are laid
           out in boxes of the same height and sit on the same line. */
        padding: 8px 14px;
        font-weight: normal;
    }}
    QToolButton#tabBarButton:hover {{
        color: {_h(TEXT_PRIMARY)};
    }}
    /* A tab's close button. Flat and bare, because all it is is the style's own
       ✕ sitting on the tab: the QToolButton rule above would otherwise wrap it in
       a raised, rounded, bordered box that looks nothing like a tab's mark. */
    QToolButton#tabCloseButton {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 0;
    }}
    QToolButton#tabBarButton:disabled {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(BORDER_SUBTLE)};
    }}
    /* A row in the bottom strip's queue: flat, and lit while hovered or while it
       is the one being dragged, so a drag reads as something the strip meant to
       offer rather than an accident. */
    QWidget#queueRow {{
        background-color: transparent;
        border-radius: 3px;
    }}
    QWidget#queueRow:hover {{
        background-color: {_h(BG_SECONDARY)};
    }}
    QWidget#queueRow[dragging="true"] {{
        background-color: {_h(BG_TERTIARY)};
        color: {_h(TEXT_MUTED)};
    }}
    /* Compact enough to ride inside a queue row, which is barely taller. */
    QPushButton#queueCancelBtn {{
        padding: 0 8px;
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
