"""The GalleryView / BrowserPane boundary, held at zero — and the split's sizes.

The audit measured the coupling no length or coverage gate can see: the pane
reached into the view 93 times (83 of them at private names, one of them a
write), the view reached back at pane privates, and 48 of the pane's 54
six-month commits also touched the view. The inversion took that to zero in
both directions; these tests are what keep it there. They read source, not
running objects, so they fire before anything is constructed and hold in both
directions symmetrically.

Every count is an EQUALITY, not a ceiling. Above the number is a new
violation; below it means a change lowered the real value and forgot to lower
the gate, which would leave that much silent headroom for the next violation
to hide in. A commit that moves a number says so, in the same commit.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VIEW = REPO_ROOT / "origenerator" / "gui" / "gallery_view.py"
PANE = REPO_ROOT / "origenerator" / "gui" / "browser_pane.py"

# A private attribute read through a privately held object — self._x._y — the
# reach-through shape the audit counted 93 of. Zero everywhere in both files:
# scoping it to one attribute name would let a renamed handle walk past it.
_REACH_THROUGH = re.compile(r"self\._[a-z_]+\._[a-z_]")


def _private_chains(path: Path) -> list[str]:
    return _REACH_THROUGH.findall(path.read_text(encoding="utf-8"))


def _ast_private_chains(path: Path) -> int:
    """The same count off the syntax tree, so a chain the regex cannot see —
    one split across lines, or oddly spaced — still counts."""
    found = 0
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Attribute) and node.attr.startswith("_")
                and isinstance(node.value, ast.Attribute)
                and node.value.attr.startswith("_")
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"):
            found += 1
    return found


def _class_def(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == name)


def test_neither_knot_file_reaches_a_private_through_a_private():
    for path in (VIEW, PANE):
        assert _private_chains(path) == [], path.name
        assert _ast_private_chains(path) == 0, path.name


def test_the_pane_holds_no_view():
    """The back-pointer stays deleted. The regex above would miss a re-added
    self._v that only called public attributes, so the handle itself is banned:
    no name in browser_pane.py mentions GalleryView, and the constructor's
    parameters are exactly the collaborators the split ended on."""
    tree = ast.parse(PANE.read_text(encoding="utf-8"))
    named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} \
        | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} \
        | {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
           for a in n.names}
    assert "GalleryView" not in named  # docstring prose may say it; code may not
    assert "_v" not in named  # the handle itself, under the name it had
    init = next(n for n in _class_def(PANE, "BrowserPane").body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert [a.arg for a in init.args.args] == [
        "self", "scroll", "db", "jobs", "auto", "tree", "host"]


def test_the_classes_hold_the_splits_sizes_as_equalities():
    """The per-class method count, ratcheted to what the inversion left.

    This is the number the audit said to gate (Q14): the god object measured
    368 methods, and a class this size only ever grows quietly. Shrink it and
    the gate shrinks with you, in the same commit; grow it and this fails,
    which is the gate doing its job. (380 → 372: the search came out as
    `GallerySearchController`, taking fourteen methods with it and adding six —
    the five the controller asks of its host, and the history guard those
    needed. Back and Forward followed as `NavigationController`: nine out,
    seven host methods and two delegations in, and those two went when the voice
    tables stopped naming their handlers as strings. 371 → 372: one folder-key
    derivation replaced the five that were written inline, and it takes a row as
    readily as a config. 372 → 371: the gallery's handle on the config tab's
    private preview widget is gone, and its two remaining drivers ask the panel. 80 → 77: the queue's cards are a join over four
    sources and no rendering at all, so they are built outside the pane now
    (`gui/inflight_items.py`) and it keeps a one-line delegation. 77 -> 74: what
    the selected collection gathers is asked of its own key, so the five answers
    written out a second time went, and with them the three predicates only that
    second copy asked. The pane keeps 74 while its three selection fields go: which
    tiles are picked, the anchor a Shift-click measures from and the order they
    are shown are a `Picking` now, so what stays are delegations, and the
    five collections are one `PaneCollection` record apiece rather than a branch in each of two
    chains. 74 -> 75: the card for a run still in flight was built by hand on
    Latest, in a folder and on Requests, and is one method now, so Requests can
    draw its cards between the time headings that split the collection into batches.
    371 -> 341:
    the fullscreen slideshows came out as `SlideshowDirector` -- thirty-two methods out,
    sixteen of what stays renamed to the host contract they now answer, and two
    new ones for what the slideshows ask that had no name of its own. 341 -> 318:
    everything spoken came out as `VoiceRouter` -- the microphone, the caption,
    and where each word lands -- twenty-five methods out and two in, the bank it
    presses now bound to it by keyword rather than looked up by name. 318 -> 291:
    the combine came out as `CombineController`, owning the panel it used to be
    handed -- thirty-five methods out, eight in, and the spoken animation going
    with the act it asks for rather than staying with the words. 291 -> 268: the
    standalone enhance came out as `EnhanceController`, owning its settings
    panel -- thirty methods out, eight in, and the bank button now lit from what
    the controller answers rather than aimed inside the gallery. 268 -> 262: the
    bank came out as `ToolbarBank`, which builds its sixteen buttons and is
    written from one `BankState` -- eleven methods out, five in, and the nine
    hand-written syncs the gallery kept in step by hand collapsed to one
    `_re_aim`. 262 -> 267: the one method that built every widget in the screen
    is six -- a pane apiece, and the two arrangers the hosted and standalone
    shapes differ in -- which is five more methods and 273 fewer lines in the
    longest one. 267 -> 270: the constructor names its four steps -- the
    collaborators handed in, the queue of runs, the slots a rebuild fills, and
    the panes' own objects -- which takes it under fifty statements for the first
    time. 270 -> 267: `SlideshowDirector` builds a double-clicked item's slides and
    every slideshow's versions from the rows the browser lists, so the three methods
    that built them here went. 267 -> 266: a folder tile's still of a combine's
    source video and a config tab's loop of it are one "what this run was made
    from", asked for once. 266 -> 265: that answer compares the run's prompts
    with its source video's, so the lookup of the source video's row folds into it. 265 -> 267:
    opening a folder lands on its first item, which wants the loading half of a
    thumbnail click without the browsing step a click records -- two methods,
    since a click's own name would be a lie on the folder open driving it. The
    three sites that opened a folder to watch the run in flight in it are one
    method now, so what used to lead them went into it. 267 -> 266: the OSR2
    switch is the only record of whether it is on, so the copy of it kept here
    went with the one method that wrote it, and the pair the session file saves
    it through reads the four control states instead of on and off. 266 -> 265:
    the two arrangers came out as `PaneArrangement`, which a Fun Time session
    taking over an open window also asks to fold the panes into its column, and
    the gallery keeps the one `become_hosted` for that. 265 -> 266: the session
    hands that window back when it ends, and `become_standalone` asks the
    arrangement to unfold them. 266 -> 267: a folder's star stopped redrawing the
    whole gallery and is told in place, as an item's always was, so re-counting
    the Favorites collection and drawing it again where it is open is one method both
    of them ask. And the pane 75 -> 77: it marks a folder's square in place, and
    reads the bookmarked folders off each side's folders when it needs them
    rather than keeping a list a star would leave stale. 267 -> 268: a Fun Time
    session names the clip its Genau has locked on by the clip's file, and
    landing on the generation that file copies is `go_to_file` -- the gallery's
    rows and a `follow_link`, which nothing outside it holds both of. 268 -> 267:
    a discarded seed's relaunch comes before the folder's redraw, so the tab
    following Auto-Generate keeps following it, and the drop and the redraw that
    `_drop_reroll` wrapped for its one caller are that caller's own lines. And the
    pane 77 -> 83: every folder of folders has its own five collections, so a collection's
    rows are asked for a folder as well as a side -- a side's placement of its
    rows, a folder's share of a list, the open collection's rows, a folder's own cards
    in flight, its starred pictures, the counts every folder's collections wear and
    the square each of them shows among the folder's own are seven methods, and
    the lister of Latest's rows they replace went. 267 -> 266: a combination
    draws fresh seeds, so it never repeats a run and the question the gallery
    put before one went. 266 -> 268: the room's keys move this app's panels too, so
    where each side's slideshow wears its panel is answered here and set from the
    session's line -- the corner and whether it is collapsed read back together,
    because a slideshow wears them together. 268 -> 270: the OSR2's max intensity is saved
    with the session beside its control state, through the pair every switch the
    session file keeps is read and put back by. And the pane 86 -> 87: a slideshow
    collects what a set holds once for each model the pane takes rather than
    once for each picture a running generation sends, and the pane's stamp is
    what says a new model has come. 270 -> 272: the slideshows -- where the last
    one was left, its filters, where each side's panel sits and the pace -- are
    saved with the session too, through that same pair. 272 -> 273: a Fun Time
    session opening while a slideshow is up takes that slideshow into the room,
    so whether one is up is asked here for the offer the window stands. 273 -> 275:
    a generation ComfyUI refuses as the app closes is saved with the session and
    said at the next launch, through that same pair. 275 -> 277: how many a press
    of Generate makes is saved with the session the same way. 277 -> 272: the
    find strip went to shared_ui, where it wires its own find, so the five
    methods that wired the two together here went with it. 272 -> 276: the folder
    list gained its Portrait / Landscape / Both radio and the Images / Videos /
    Both choice moved to the pane that lists the items, so the view answers the
    radio, offers or hides the kinds, keeps each side's list against the library
    it was built from, and re-counts the collections on their own. And the pane
    87 -> 88: a pane drawn over another takes back the tiles it would build again
    the same, so the three places that built a tile hand their row to the one
    method that takes it back or builds it. 276 -> 274: a double-click on a
    folder in the list opens or closes it and renames nothing, so the two methods
    that opened its name for typing and saved what was typed went. 274 -> 272:
    Rename... left the folder list's menus too, and with it the dialog that asked
    for the name and the step that saved it. 272 -> 274: a Fun Time session hands
    each Satellite Funestra over on its own, so the session's bridge fills one
    side's region and gives one side back through two more. 274 -> 275: the panes
    fold for the rect a session on the monitors names and sit side by side in a
    headset room, so which shape they wear is one question, asked at a takeover
    and at each crossing. 275 -> 276: a folder Auto-Generate runs in takes a
    star, as a folder dropped onto Favorites does, so putting a folder's star
    where it is asked to be -- which the star's own toggle, that drop and the
    Auto-Generate all ask -- is one method. 276 -> 277: a spoken "animate as" is
    Combine's to answer, through a forwarder of its own. 277 -> 276: "genau it"
    went with the prompt-read act it ran on, so that one forwarder answers every
    spoken animation. And the pane 88 -> 87: work in flight already sits in its
    side's folder list, which is what keeps that side's Latest up, so the shapes
    the work in flight comes in are no longer asked for. 276 -> 277: the surface
    in front -- a slideshow while one is up, else the front tab -- is one method
    the OSR2 and a "Video ready" notice both ask, in place of the OSR2's own, and
    the video playing on it is the other. 277 -> 285: Separate or
    Together, Images / Videos / Both, the folders left open and the console's
    motion are saved with the session through that same pair, four pairs; where
    each border was dragged is the window's own, kept beside its geometry, and
    which folders are open is the TOC's. And the pane 87 -> 86: a tile is
    captioned with its item's name, which the gallery's one set of names
    answers, so the pane's own caption-maker went. 285 -> 280: Images and
    Videos are folders in the list again, each with its own five collections,
    so the five methods that offered the Images / Videos / Both choice,
    answered it, said what it held and saved and restored it went. And the
    pane 86 -> 85: another Latest opens on its first page by itself, so the
    step that choice asked for went.
    280 -> 279: the session opens each side on its own, so the open of both
    at once, which nothing sends now, went. 279 -> 281: the session hears the
    rest of a spoken request it posted here, so whether one is being taken, and
    dropping one whose slideshow closed, are two forwarders to the voice.
    281 -> 278: Esc pauses the room rather than stopping everything and
    putting it back, so the four methods that read, stopped and restarted
    what was running went, and one asks whether the OSR2 is moving. 278 -> 277:
    Esc in a text field is the field's even while the OSR2 moves, so that
    question went too. 277 -> 278: Ctrl+C copies the names of what is picked,
    the way Delete deletes it, so it is one method beside Delete's. 278 -> 279:
    a lock in the room, a lock on one of the app's own slideshows and a clicked
    notice each put their item in front of him through one method, which asks
    a hosting room for this window's place. 279 -> 280: Start now ends the
    minute a video waits after a picture, from the job queue or a slideshow's,
    so it is one method beside Clear's. 280 -> 281: an item dragged over a
    folder of your own in the TOC goes in only where the gallery shows it on
    that folder's side, which the TOC asks of the gallery through one
    method. 281 -> 282: the middle pane takes a drag while a folder of your own
    is open in it, and asks the TOC what that folder's own row would take,
    through one method. 282 -> 283: a folder of your own can go inside another,
    so which dragged folders a row in the TOC takes is the gallery's to answer
    too, through one more. And the pane 85 -> 84: every drag the app starts
    reaches every place it could drop by itself, so the pane's relay of its
    tiles' drags to Combine went. 283 -> 281: each step of the path over the
    pictures opens its folder and a copy button copies the path, so the two
    methods that opened the path for typing and went where a typed path led went.
    281 -> 280: a collection's path wears its star as the family's mark, which the
    header sets in ahead of the step's name, so the method that typed the star into
    that name went. 280 -> 276: what the app does with the graphics card while it
    is closed is started by Evolver, so the two batches the closing gallery queued,
    and their two launch adapters, went to origenerator.downtime. 276 -> 274: a run
    ComfyUI refuses as the app closes waits for the next launch to send it, so the
    pair that kept its message for then went. 274 -> 271: what the microphone hears
    no longer edits the prompt Auto-Generate runs on, so the two methods voice read
    and wrote that prompt through went, and so did the one that found the folder an
    edited prompt belonged in. And the pane 84 -> 82: Latest's pages are drawn by
    the one pager any listing can take, so the three steps that drew, forgot and
    revealed Latest's own pages are the one that hands a listing to it.)"""
    assert sum(isinstance(x, ast.FunctionDef)
               for x in _class_def(VIEW, "GalleryView").body) == 271
    assert sum(isinstance(x, ast.FunctionDef)
               for x in _class_def(PANE, "BrowserPane").body) == 81
