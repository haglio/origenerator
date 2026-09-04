from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import (
    BG_BUTTON,
    BG_BUTTON_ACTIVE,
    BG_KEYCAP,
    BG_PRIMARY,
    BG_SECONDARY,
    BG_TERTIARY,
    BLUE,
    BORDER_PANEL,
    BORDER_SUBTLE,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
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
    /* A radio's mark, drawn here rather than left to the platform. The app-wide
       QWidget rule above hands every radio to the stylesheet engine, and the
       selected mark it falls back to paints dark on this dark ground — the
       chosen Players/Genau lane simply vanished. So both states are stated here:
       the same hairline ring the fields wear, and inside it a light disc a
       couple of pixels short of that ring. The disc is a radial gradient because
       Qt draws no shapes for a subcontrol and takes a picture only as a file
       (see _spin_arrow_rules above); a gradient also stays crisp at any screen
       scale, and its two stops sit a hair apart rather than hard against each
       other so the disc's edge reads smooth instead of stepped. */
    QRadioButton::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 8px;
        background-color: {_h(BG_SECONDARY)};
    }}
    QRadioButton::indicator:checked {{
        background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0.66 {_h(TEXT_PRIMARY)}, stop:0.78 {_h(BG_SECONDARY)});
    }}
    /* Every right-click menu in the app. The app-wide QWidget rule above paints a
       menu's items on the same flat background as the menu itself, which leaves
       the row under the cursor looking exactly like the rows either side of it —
       so a menu gives no sign of what a click would land on. These put the
       highlight back, in the same blue a dropdown marks its rows with. */
    QMenu {{
        background-color: {_h(BG_TERTIARY)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        padding: 4px 0;
    }}
    QMenu::item {{
        /* Room for the highlight to read as a band across the row rather than a
           rectangle crowding the text. */
        padding: 6px 20px;
        background-color: transparent;
    }}
    QMenu::item:selected {{
        background-color: {_h(BLUE)};
        color: {_h(TEXT_PRIMARY)};
    }}
    QMenu::item:disabled {{
        color: {_h(TEXT_MUTED)};
    }}
    QMenu::item:disabled:selected {{
        /* Hovering something unclickable must not promise a click. */
        background-color: transparent;
        color: {_h(TEXT_MUTED)};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {_h(BORDER_SUBTLE)};
        margin: 4px 0;
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
    QPushButton:checked {{
        background-color: {_h(BG_BUTTON_ACTIVE)};
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
    /* A read-only gallery (no ComfyUI client) can never launch, so Generate greys
       out; the id selector above out-specifies the base :disabled rule, so restate
       it here. */
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
    /* A control that is ON sits on a lighter ground than one at rest -- one rule
       across the family, so a toggled button reads the same whichever app it is
       in. The blue below is the one exception, for a state that means more than
       "engaged". */
    QToolButton:checked {{
        background-color: {_h(BG_BUTTON_ACTIVE)};
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
        /* The horizontal padding is where a tab's contents begin, so it is what
           sets the gap in front of its mark. It matches the one the ✕ leaves at
           the other end (eliding_tab_bar.EDGE), or a tab reads as two separate
           decisions rather than one row. */
        padding: 8px 10px;
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
    /* A tab's close button. Flat and bare, because all it is is the style's own
       ✕ sitting on the tab: the default QToolButton look would wrap it in a
       raised, rounded, bordered box that looks nothing like a tab's mark. */
    QToolButton#tabCloseButton {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 0;
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
    /* The fold header over each model+LoRA band of search results. Brighter
       than the muted captions and ruled off above, so it reads as the start of
       a section rather than as a label belonging to the tiles before it; left
       aligned and transparent so a flat button reads as a heading you can
       click rather than as a button that happens to be wide. */
    QPushButton#sectionHeading {{
        color: {_h(TEXT_PRIMARY)};
        font-weight: bold;
        background: transparent;
        border: none;
        border-top: 1px solid {_h(BORDER_SUBTLE)};
        padding: 6px 0 2px 0;
        text-align: left;
    }}
    QPushButton#sectionHeading:hover {{
        color: {_h(BLUE)};
    }}
    /* The standing label over each half of the TOC pane, naming the shape that
       half holds. Outside the tree rather than a row in it, so it is still on
       screen when the rows under it have scrolled; ruled off below so it reads
       as the head of the list rather than as its first entry. The frame carries
       the rule and the padding because its proportion mark and its word both sit
       inside them. */
    QFrame#treeSectionLabel {{
        background: transparent;
        border-bottom: 1px solid {_h(BORDER_SUBTLE)};
        padding: 4px 2px 3px 2px;
    }}
    /* Qt style sheets do not hand a parent's color down to its children, so the
       heading's word states its own; the mark beside it is drawn, not styled. */
    QLabel#treeSectionName {{
        color: {_h(TEXT_PRIMARY)};
        font-weight: bold;
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
