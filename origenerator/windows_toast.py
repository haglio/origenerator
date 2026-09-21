"""Windows' own notification, raised by an app nothing ever installed.

A toast carries a link Windows follows on a click, hours later and with the app
closed (:mod:`origenerator.app_link`), where the tray icon's balloon this app
used first died with the app and had nowhere to send a click. The
AppUserModelId entry that gives a notice its heading and its mark is also what
makes a toast raisable at all, measured on 2026-09-21 against a docstring that
said this route needs a Start menu shortcut.

Called through ctypes rather than a package: four objects and five calls.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

_combase = ctypes.windll.combase  # type: ignore[attr-defined]
_ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]

_TOAST_MANAGER = "Windows.UI.Notifications.ToastNotificationManager"
_TOAST = "Windows.UI.Notifications.ToastNotification"
_XML_DOCUMENT = "Windows.Data.Xml.Dom.XmlDocument"

_MANAGER_STATICS = "50ac103f-d235-4598-bbef-98fe4d1a3ad4"
_TOAST_FACTORY = "04124b20-82c6-4229-b109-fd9ed4662b53"
_XML_DOCUMENT_IO = "6cd0e74e-ee65-4489-9ebf-ca43e87ba637"
_XML_DOCUMENT_IID = "f7f3a506-1e87-42d6-bcfb-b8c809fa5494"

# Where each call sits in its interface's table: the three IUnknown entries and
# IInspectable's three come first, so everything an interface of its own
# declares starts at six.
_QUERY_INTERFACE = 0
_RELEASE = 2
_CREATE_NOTIFIER_WITH_ID = 7
_LOAD_XML = 6
_CREATE_TOAST = 6
_SHOW = 6

_RO_INIT_MULTITHREADED = 1


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def toast_xml(title: str, body: str, *, link: str, mark: Path | None = None) -> str:
    """What Windows draws for one notice, and where a click on it goes."""
    glyph = (f"<image placement=\"appLogoOverride\" src={quoteattr(mark.as_uri())}/>"
             if mark is not None else "")
    return (
        f"<toast activationType=\"protocol\" launch={quoteattr(link)}>"
        "<visual><binding template=\"ToastGeneric\">"
        f"<text>{escape(title)}</text><text>{escape(body)}</text>{glyph}"
        "</binding></visual></toast>"
    )


def show(app_id: str, xml: str) -> None:
    """Raise the notification *xml* describes, as the app *app_id* names."""
    notifier = _notifier_for(app_id)
    document = document_of(xml)
    toast = _toast_of(document)
    try:
        _call(notifier, _SHOW, toast, types=(ctypes.c_void_p,))
    finally:
        for held in (toast, document, notifier):
            _release(held)


def document_of(xml: str):
    """*xml* as the document Windows reads a notification out of.

    Raises ``OSError`` where Windows cannot read it — a toast it cannot parse
    is a notification that never appears, with nothing on screen to say so.
    """
    document = _activate(_XML_DOCUMENT)
    reader = _as(document, _XML_DOCUMENT_IO)
    try:
        with _text(xml) as raw:
            _call(reader, _LOAD_XML, raw, types=(ctypes.c_void_p,))
    finally:
        _release(reader)
    return document


def _toast_of(document):
    """The notification *document* describes. The document stays the caller's."""
    factory = _factory(_TOAST, _TOAST_FACTORY)
    read_as_a_document = _as(document, _XML_DOCUMENT_IID)
    toast = ctypes.c_void_p()
    try:
        _call(factory, _CREATE_TOAST, read_as_a_document, ctypes.byref(toast),
              types=(ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)))
    finally:
        _release(read_as_a_document)
        _release(factory)
    return toast


def _notifier_for(app_id: str):
    statics = _factory(_TOAST_MANAGER, _MANAGER_STATICS)
    notifier = ctypes.c_void_p()
    try:
        with _text(app_id) as named:
            _call(statics, _CREATE_NOTIFIER_WITH_ID, named, ctypes.byref(notifier),
                  types=(ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)))
    finally:
        _release(statics)
    return notifier


class _text:
    """A string in the form the runtime takes, for as long as a call needs it."""

    def __init__(self, value: str):
        self._value = value
        self._handle = ctypes.c_void_p()

    def __enter__(self) -> ctypes.c_void_p:
        _raise_on(_combase.WindowsCreateString(
            ctypes.c_wchar_p(self._value), ctypes.c_uint32(len(self._value)),
            ctypes.byref(self._handle)), "WindowsCreateString")
        return self._handle

    def __exit__(self, *_):
        _combase.WindowsDeleteString(self._handle)


def _guid(text: str) -> _GUID:
    value = _GUID()
    _raise_on(_ole32.IIDFromString(ctypes.c_wchar_p("{" + text + "}"),
                                  ctypes.byref(value)), "IIDFromString")
    return value


def _factory(runtime_class: str, iid: str):
    _combase.RoInitialize(_RO_INIT_MULTITHREADED)  # already-initialized is a no-op
    factory = ctypes.c_void_p()
    with _text(runtime_class) as named:
        _raise_on(_combase.RoGetActivationFactory(
            named, ctypes.byref(_guid(iid)), ctypes.byref(factory)), runtime_class)
    return factory


def _activate(runtime_class: str):
    _combase.RoInitialize(_RO_INIT_MULTITHREADED)
    instance = ctypes.c_void_p()
    with _text(runtime_class) as named:
        _raise_on(_combase.RoActivateInstance(named, ctypes.byref(instance)),
                  runtime_class)
    return instance


def _as(interface, iid: str):
    """*interface* seen through another of its faces."""
    face = ctypes.c_void_p()
    _call(interface, _QUERY_INTERFACE, ctypes.byref(_guid(iid)), ctypes.byref(face),
          types=(ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)))
    return face


def _release(interface) -> None:
    """Let go of one of these objects. Everything here creates and lets go
    itself: they are reference-counted, and a notification every few minutes
    holding four of them for the life of the app would be a leak with no end."""
    _call(interface, _RELEASE, restype=ctypes.c_uint32)


def _call(interface, index: int, *arguments, types=(), restype=ctypes.c_int32):
    """Make the call sitting at *index* in *interface*'s table."""
    table = ctypes.cast(interface,
                        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    signature = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *types)
    result = signature(table[index])(interface, *arguments)
    if restype is ctypes.c_int32:
        _raise_on(result, f"call {index}")


def _raise_on(result: int, what: str) -> None:
    if result:
        raise OSError(f"{what} failed: 0x{result & 0xFFFFFFFF:08X}")
