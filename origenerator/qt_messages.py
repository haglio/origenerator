from __future__ import annotations

import logging

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}

logger = logging.getLogger("qt")


def log_qt_message(kind, _context, message: str) -> None:
    logger.log(_LEVELS.get(kind, logging.WARNING), "%s", message)


def install_qt_message_logging():
    return qInstallMessageHandler(log_qt_message)
