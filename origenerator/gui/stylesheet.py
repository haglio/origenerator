from __future__ import annotations

from shared_ui import palette
from shared_ui.chrome import control_ground, family_stylesheet, field_rules, tool_button_rules
from shared_ui.colors import (
    BG_SECONDARY,
    BG_TERTIARY,
    BLUE,
    BORDER_PANEL,
    BORDER_SUBTLE,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    YELLOW,
    family_palette,
    hovered,
)
from shared_ui.preview import Preview
from shared_ui.preview_icon import app_icon
from shared_ui.spacing import (
    BUTTON_ICON_INSET,
    BUTTON_PAD_H_TIGHT,
    BUTTON_PAD_V,
    BUTTON_RADIUS,
    GAP_MEDIUM,
    GAP_SMALL,
    MARGIN_STANDARD,
)

from origenerator.config import PROJECT_DIR
from origenerator.gui import drop_style
from origenerator.gui.eliding_tab_bar import EDGE
from origenerator.gui.panes import BORDER_NAME, BORDERED_SET
from origenerator.gui.tooltip_shape import shape_long_tooltips
from origenerator.spin_arrows import arrow_paths

# Set on a button whose ON state says a choice has been made rather than that
# the control is engaged, which is what the blue below is for.
CHOSEN = "chosen"
CHOSEN_CONTROL = f'QAbstractButton[{CHOSEN}="true"]:checked'

# Set on the one button in a window that commits the decision the window exists
# to make, so it wears the blue rather than sitting among its neighbors.
COMMITS = "commits"
COMMITTING_CONTROL = f'QPushButton[{COMMITS}="true"]'


def _h(color) -> str:
    return color.name()


_ARROW_ROOM = 16
_RADIO_MARK = 14
_RING = 1

_STEP_BUTTONS = ("QSpinBox::up-button", "QDoubleSpinBox::up-button",
                 "QSpinBox::down-button", "QDoubleSpinBox::down-button")


def _drawn_arrow_rules() -> str:
    """The arrows of the step buttons and of Generate's dropdown, as ``image:``
    rules over generated triangles.

    Qt takes an arrow only as an image — the CSS zero-size-element-with-borders triangle
    draws a filled rectangle here, which is what appeared over the buttons — so
    :mod:`origenerator.spin_arrows` renders one. If it can't, this contributes
    nothing and Qt draws its own arrow: uncertain color, but an arrow.
    """
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
    }}
    QComboBox#howMany::down-arrow {{
        image: url("{normal[1]}");
    }}
    QComboBox#howMany::down-arrow:disabled {{
        image: url("{muted[1]}");
    }}"""


def build_stylesheet() -> str:
    """The family's sheet -- ground, tooltip, menus, push buttons -- with this
    app's own rules after it, where a later rule of equal weight wins and an
    id out-specifies anything the family says."""
    return f"""
{family_stylesheet()}
    QLabel {{
        color: {_h(TEXT_SECONDARY)};
    }}
    /* A scene's heading: set off from the form's keys around it, the way
       a section's header is, so a story reads as scenes and not as more keys. */
    QLabel#sceneTitle {{
        color: {_h(TEXT_PRIMARY)};
        font-weight: bold;
    }}
    /* Fields that belong together -- a scene's texts and its length, a fix's
       edit button, checkbox, name and value -- bordered, so each set reads as
       one thing rather than as loose fields. */
    QFrame#{BORDERED_SET} {{
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: {BUTTON_RADIUS}px;
    }}
    /* A prompt the run would ignore and its label (prompt_boxes.set_in_use marks
       both "inert"): dim, so a field you cannot type into doesn't read as one
       you simply haven't filled in yet. */
    QPlainTextEdit[inert="true"], QLabel[inert="true"] {{
        color: {_h(TEXT_MUTED)};
    }}
    QLabel#estimateLabel {{
        color: {_h(TEXT_MUTED)};
    }}
    QLabel#dimensionsHint {{
        color: {_h(TEXT_MUTED)};
    }}
    QLabel#cannotRemakeNote {{
        color: {_h(YELLOW)};
    }}
{field_rules()}
    QSpinBox, QDoubleSpinBox {{
        /* Room for the step buttons, so the value never runs under them. */
        padding-right: {_ARROW_ROOM + GAP_SMALL}px;
    }}
    /* Styling a spinner at all hands Qt the whole widget, step buttons
       included — and the default it falls back to for them has no size, so the
       arrows render as dead slivers you cannot hit. Give them a real size and a
       drawn arrow and they work again. */
    {", ".join(_STEP_BUTTONS)} {{
        subcontrol-origin: border;
        width: {_ARROW_ROOM}px;
        border-left: 1px solid {_h(BORDER_SUBTLE)};
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-position: top right;
        border-top-right-radius: {BUTTON_RADIUS}px;
    }}
    /* No placement: Qt's own default for a down-button is the low right corner,
       which is where this one goes. The radius is uniform because a QSS radius
       is only settable per corner or for all four, and the corner that matters
       is the outer one, where the field's own rounding is. */
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        border-top: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: {BUTTON_RADIUS}px;
    }}
{control_ground(palette.BG_BUTTON, *_STEP_BUTTONS)}
    QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
    QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
        background-color: {_h(BLUE)};
    }}
{_drawn_arrow_rules()}
    QComboBox {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_PRIMARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: {BUTTON_RADIUS}px;
        padding: {BUTTON_PAD_V}px {MARGIN_STANDARD}px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {_h(BG_TERTIARY)};
        color: {_h(TEXT_PRIMARY)};
        selection-background-color: {_h(BLUE)};
    }}
    QComboBox QAbstractItemView::item:disabled {{
        /* The rule above colors every item, disabled ones included, so an
           unpickable entry would look exactly as pickable as the rest. Mute it. */
        color: {_h(TEXT_MUTED)};
    }}
    /* A radio's mark, drawn here rather than left to the platform. The app-wide
       QWidget rule above hands every radio to the stylesheet engine, and the
       selected mark it falls back to paints dark on this dark ground — the
       chosen Video/Genau lane simply vanished. So both states are stated here:
       the same hairline ring the fields wear, and inside it a light disc a
       couple of pixels short of that ring. The disc is a radial gradient because
       Qt draws no shapes for a subcontrol and takes an image only as a file
       (see _drawn_arrow_rules above); a gradient also stays crisp at any screen
       scale, and its two stops sit a hair apart rather than hard against each
       other so the disc's edge reads smooth instead of stepped. */
    /* The family's small gap, short of the stock six pixels: at six, each word
       sat nearer the next circle than its own, which reads as labeling the wrong
       one. */
    QRadioButton {{
        spacing: {GAP_SMALL}px;
    }}
    QRadioButton::indicator {{
        width: {_RADIO_MARK}px;
        height: {_RADIO_MARK}px;
        border: {_RING}px solid {_h(BORDER_SUBTLE)};
        border-radius: {_RADIO_MARK // 2 + _RING}px;
        background-color: {_h(BG_SECONDARY)};
    }}
    QRadioButton::indicator:checked {{
        background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0.66 {_h(TEXT_PRIMARY)}, stop:0.78 {_h(BG_SECONDARY)});
    }}
    /* Generate is set apart by color and weight only, not size, so it sits the
       same height as the other buttons in its row — one consistent button size,
       not a taller primary. */
    QPushButton#generateBtn {{
        background-color: {_h(BLUE)};
        font-weight: bold;
    }}
    QPushButton#generateBtn:hover {{
        background-color: {_h(hovered(BLUE))};
    }}
    QFrame#generateWithHowMany {{
        background-color: {_h(BLUE)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: {BUTTON_RADIUS}px;
    }}
    QFrame#generateWithHowMany:disabled {{
        background-color: {_h(BG_SECONDARY)};
    }}
    QFrame#generateWithHowMany QPushButton#generateBtn {{
        background-color: transparent;
        border: none;
    }}
    QComboBox#howMany {{
        background-color: transparent;
        font-weight: bold;
        border: none;
        border-left: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: 0px;
    }}
    QComboBox#howMany:disabled {{
        color: {_h(TEXT_MUTED)};
    }}
    QComboBox#howMany::drop-down {{
        border: none;
        width: {_ARROW_ROOM}px;
    }}
    /* Generate grays out while it cannot launch; the id selector above
       out-specifies the base :disabled rule, so restate it here. */
    QPushButton#generateBtn:disabled {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_MUTED)};
    }}
    /* A collapsible param-form section header: a flat, full-width divider row,
       not a raised button. Left-aligned with its fold arrow, and it must not
       flash the primary blue on click the way the base :pressed rule would. */
    QPushButton#foldingSectionHeader {{
        background-color: transparent;
        color: {_h(TEXT_PRIMARY)};
        border-style: solid;
        border-color: {_h(BORDER_SUBTLE)};
        border-width: 0 0 1px 0;
        border-radius: 0;
        text-align: left;
        font-weight: bold;
        padding: {BUTTON_PAD_V}px {GAP_SMALL}px;
    }}
    QPushButton#foldingSectionHeader:hover {{
        background-color: {_h(BG_SECONDARY)};
    }}
    QPushButton#foldingSectionHeader:pressed {{
        background-color: {_h(BG_SECONDARY)};
    }}
{tool_button_rules()}
    /* The derived-size padlock: a compact toggle floating between the width and
       height rows. Its own blue comes from the rule below. */
    QToolButton#dimensionUnlock {{
        padding: {BUTTON_ICON_INSET}px {GAP_SMALL}px;
    }}
    /* The one exception to the on-ground rule above: a control whose ON state
       means a choice has been made wears the blue every other selection does,
       keyed off the property rather than each control's name. */
{control_ground(palette.BLUE, CHOSEN_CONTROL, COMMITTING_CONTROL)}
    QProgressBar {{
        background-color: {_h(BG_SECONDARY)};
        border: 1px solid {_h(BORDER_SUBTLE)};
        border-radius: {BUTTON_RADIUS}px;
        text-align: center;
        color: {_h(TEXT_PRIMARY)};
    }}
    QProgressBar::chunk {{
        background-color: {_h(BLUE)};
    }}
    QScrollArea {{
        border: none;
    }}
    /* No frame round a tab's contents: the panes on either side of the info
       pane are parted from it by a splitter handle, and a hairline inside that
       is a second boundary saying the same thing — one that also held the
       settings' own handle a couple of pixels short of the pane's edge. */
    QTabWidget::pane {{
        border: none;
    }}
    QSplitter::handle, QFrame#{BORDER_NAME} {{
        background-color: {_h(BG_SECONDARY)};
    }}
    QSplitter::handle:hover {{
        background-color: {_h(BLUE)};
    }}
    QTabBar::tab {{
        background-color: {_h(BG_SECONDARY)};
        color: {_h(TEXT_MUTED)};
        /* The horizontal padding is where a tab's contents begin, so it is what
           sets the gap in front of its mark. It matches the one the cross leaves at
           the other end (eliding_tab_bar.EDGE), or a tab reads as two separate
           decisions rather than one row. */
        padding: {GAP_MEDIUM}px {EDGE}px;
        /* A hairline between tabs, so it reads which cross belongs to which, over a
           rule the selected tab alone colors in. One declaration each way round,
           since the two edges differ in width and in color: top, right, low,
           left. */
        border-style: solid;
        border-color: transparent {_h(BORDER_SUBTLE)} transparent transparent;
        border-width: 0 1px 2px 0;
    }}
    QTabBar::tab:selected {{
        color: {_h(TEXT_PRIMARY)};
        border-color: transparent {_h(BORDER_SUBTLE)} {_h(BLUE)} transparent;
    }}
    QTabBar::tab:hover {{
        color: {_h(TEXT_PRIMARY)};
    }}
    /* A tab's close button, and a scene's remove. Flat and bare, because
       all it is is the family's cross sitting on the tab: the default QToolButton
       look would wrap it in a raised, rounded, bordered frame that looks nothing
       like a tab's mark. */
    QToolButton#tabCloseButton, QToolButton#sceneRemove {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 0;
    }}
    /* A row in the Job Queue: flat, and lit while hovered or while it
       is the one being dragged, so a drag reads as something the Job Queue meant to
       offer rather than an accident. */
    QWidget#queueRow {{
        background-color: transparent;
        border-radius: {BUTTON_RADIUS}px;
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
        padding: 0 {BUTTON_PAD_H_TIGHT}px;
    }}
    QLabel#combineHeading {{
        color: {_h(TEXT_MUTED)};
        font-weight: bold;
        padding: {GAP_SMALL}px 0;
    }}
    /* The fold header over each model+LoRA section of search results, and the
       time heading over each batch of tiles. Brighter
       than the muted captions and ruled off above, so it reads as the start of
       a section rather than as a label belonging to the tiles before it; left
       aligned and transparent so a flat button reads as a heading you can
       click rather than as a button that happens to be wide. */
    QPushButton#tileGroupHeading, QLabel#tileGroupHeading {{
        color: {_h(TEXT_PRIMARY)};
        font-weight: bold;
        background: transparent;
        border: none;
        border-top: 1px solid {_h(BORDER_SUBTLE)};
        padding: {GAP_MEDIUM}px 0 {GAP_SMALL}px 0;
        text-align: left;
    }}
    QPushButton#tileGroupHeading:hover {{
        color: {_h(BLUE)};
    }}
    /* The picked row in the tree of contents, marked by its ground alone.
       Left to the platform, a picked row also wears an accent bar down its left
       edge, which lands on the mark the row leads with and says nothing the
       blue ground has not said already. Naming the ground here is what takes a
       picked row's painting off the platform, bar and all. */
    QTreeView::item:selected {{
        background-color: {_h(BLUE)};
        color: {_h(TEXT_PRIMARY)};
    }}
    /* The standing label over each half of the TOC pane, naming the shape that
       half holds. Outside the tree rather than a row in it, so it is still on
       screen when the rows under it have scrolled. */
    QFrame#treeSectionLabel {{
        background: transparent;
    }}
    QFrame#treeSectionRule {{
        border-style: solid;
        border-color: {_h(BORDER_SUBTLE)};
        border-width: 0 0 1px 0;
    }}
    /* Qt style sheets do not hand a parent's color down to its children, so the
       heading's word states its own; the mark beside it is drawn, not styled. */
    QLabel#treeSectionName {{
        color: {_h(TEXT_PRIMARY)};
        font-weight: bold;
    }}
    QLabel#dropZone {{
        border: 1px dashed {_h(BORDER_PANEL)};
        border-radius: {drop_style.RADIUS}px;
        color: {_h(TEXT_MUTED)};
        padding: {MARGIN_STANDARD}px;
    }}
    QLabel#dropZone[{drop_style.LIT}="true"], QLabel#dropZone[{drop_style.AIMED}="true"] {{
        border: 1px solid {_h(drop_style.EDGE)};
        color: {_h(TEXT_PRIMARY)};
    }}
    /* What fills a pane that takes drops is clear, so the pane's own ground
       shows through it when the drop zones' style lights the pane. */
    BrowserScrollArea > QWidget#qt_scrollarea_viewport > .QWidget,
    QWidget#enhancePanel .QWidget, QWidget#enhancePanel QLabel,
    QScrollArea#enhanceSettings {{
        background-color: transparent;
    }}{drop_style.ground_rules()}
    """


def dress_application(app, preview: Preview | None) -> None:
    """Put the family's palette, this app's sheet and its icon on the QApplication.

    The application and not a window, for three reasons that arrived separately.
    A QToolTip popup is a top-level widget no window-level sheet reaches, so
    styling per window left every tooltip on the native Windows 11 dark palette
    -- unreadable, which is to say missing.  And a palette is the application's
    to begin with: a sheet dresses the widgets it names, while the colors it
    names none of -- a selection's ground, a link's ink -- stay whatever the
    desktop handed the app, which here was the user's accent orange.  The icon
    is the third: a slideshow on a satellite region is a window of its own that sets
    none, and the window switcher drew it a blank page.
    """
    app.setPalette(family_palette(app.palette()))
    app.setStyleSheet(build_stylesheet())
    app.setWindowIcon(app_icon(PROJECT_DIR / "icon.ico", preview))
    shape_long_tooltips(app)
