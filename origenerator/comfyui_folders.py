from __future__ import annotations

from origenerator import config
from origenerator.comfyui_inputs import ComfyFolders
from origenerator.db_connection import SqliteFile
from origenerator.db_trash import TrashStore

COMFYUI_FOLDERS = ComfyFolders(input=config.COMFYUI_INPUT_DIR, places=config.OUTPUT_PLACES,
                               temp=config.COMFYUI_TEMP_DIR,
                               trashed=TrashStore(SqliteFile(config.DB_PATH)).trashed_file)
