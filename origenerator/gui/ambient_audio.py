"""The audio bed: several library clips playing at once, sound only.

The gallery's audio switch turns this on.  It runs one media player per voice
with no video surface attached anywhere -- and, once a clip loads, with its video
track deselected outright -- so the files are videos but all that reaches the
room is their sound.  Each player is fed by its own walk through the clip set
(:mod:`origenerator.ambient_audio`), taking the next clip the moment the current
one ends.  Nothing else in the app touches it: it plays under whatever the user
is doing until it's switched off.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from origenerator.ambient_audio import AmbientRotation, find_clips
from origenerator.config import AMBIENT_AUDIO_DIR, AMBIENT_AUDIO_VOICES

logger = logging.getLogger(__name__)


class AmbientAudio(QObject):
    """The audio bed's players -- built when it starts, released when it stops."""

    def __init__(self, parent=None, *, clips_dir=AMBIENT_AUDIO_DIR,
                 voices: int = AMBIENT_AUDIO_VOICES, make_player=None):
        super().__init__(parent)
        self._clips_dir = clips_dir
        self._voices = voices
        # Injectable so unit tests can drive playback intent without spinning up
        # the real (WMF) backend, the same seam the preview and slideshow use.
        self._make_player = make_player if make_player is not None else self._real_player
        self._players: list = []
        self._rotation: AmbientRotation | None = None

    def is_running(self) -> bool:
        """Whether the bed currently holds players (i.e. is making sound)."""
        return bool(self._players)

    def start(self) -> None:
        """Fill every voice and play.

        A no-op when already running, and silent -- with one line in the log --
        when the overlay names no clip folder or that folder holds no videos,
        which is what a public checkout has.  The switch stays on either way, so
        a folder that appears later is picked up by the next toggle.
        """
        if self._players:
            return
        clips = find_clips(self._clips_dir)
        if not clips:
            logger.info(
                "Ambient audio: no clips under %s — staying silent", self._clips_dir)
            return
        self._rotation = AmbientRotation(clips, self._voices)
        for voice in range(self._voices):
            player = self._make_player()
            player.mediaStatusChanged.connect(
                lambda status, v=voice: self._on_status(v, status))
            self._players.append(player)
        logger.info("Ambient audio: %d voices over %d clips", self._voices, len(clips))
        for voice in range(self._voices):
            self._advance(voice)

    def stop(self) -> None:
        """Silence every voice and release its player.

        The rotation is dropped first, so a status change arriving out of the
        teardown itself can't hand a dying voice one more clip.
        """
        self._rotation = None
        players, self._players = self._players, []
        for player in players:
            player.stop()
            player.setSource(QUrl())

    # --- one voice -----------------------------------------------------------

    def _advance(self, voice: int) -> None:
        """Put the voice's next clip on and play it."""
        if self._rotation is None or voice >= len(self._players):
            return
        clip = self._rotation.next_clip(voice)
        if clip is None:
            return
        player = self._players[voice]
        player.setSource(QUrl.fromLocalFile(str(clip)))
        player.play()

    def _on_status(self, voice: int, status) -> None:
        """Follow one voice's clip through its life.

        On load its video track is deselected: no sink is attached, so those
        frames are decoded for nobody, and dropping them halves what the bed
        costs the CPU -- which matters on a machine also running ComfyUI
        (measured at 0.75s -> 0.38s of CPU over five seconds of three voices).
        At the end -- or on a clip that won't decode at all -- the voice moves
        on; the others are untouched, each keeping its own place in its own pass.
        """
        if voice >= len(self._players):
            return  # a status change out of the teardown: this voice is gone
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._players[voice].setActiveVideoTrack(-1)  # -1 deselects it
        elif status in (QMediaPlayer.MediaStatus.EndOfMedia,
                        QMediaPlayer.MediaStatus.InvalidMedia):
            self._advance(voice)

    def _real_player(self) -> QMediaPlayer:
        """One voice's player: audio out, no video out, one clip at a time.

        The audio sink is parented to the player so it lives exactly as long as
        the voice does -- ``setAudioOutput`` doesn't take ownership, and a sink
        collected early leaves a player that runs silently.
        """
        player = QMediaPlayer(self)
        output = QAudioOutput(player)
        player.setAudioOutput(output)
        player.setLoops(QMediaPlayer.Loops.Once)  # one clip, then the next
        return player
