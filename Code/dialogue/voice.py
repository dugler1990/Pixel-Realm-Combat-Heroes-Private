import os

import pygame


class VoiceChannel:
    """One voice slot. A missing file is silence, not an error.

    `loader` is a test seam: `(audio_key) -> sound or None`. The sound needs
    `play()` and `stop()`.
    """

    def __init__(self, loader=None, root=None):
        self.loader = loader
        self.root = root
        self._sounds = {}
        self._current = None

    def play(self, audio_key, enabled=True):
        if not enabled or not audio_key:
            self.stop()
            return False
        sound = self._load(audio_key)
        if sound is None:
            return False
        self.stop()
        sound.play()
        self._current = sound
        return True

    def stop(self):
        if self._current is None:
            return
        stop = getattr(self._current, "stop", None)
        if stop is not None:
            stop()
        self._current = None

    def _load(self, audio_key):
        if audio_key in self._sounds:
            return self._sounds[audio_key]
        if self.loader is not None:
            sound = self.loader(audio_key)
        else:
            sound = _load_file(audio_key, self.root)
        self._sounds[audio_key] = sound
        return sound


def _load_file(audio_key, root):
    path = audio_key
    if root and not os.path.isabs(path):
        path = os.path.join(root, audio_key)
    if not os.path.isfile(path):
        return None
    return pygame.mixer.Sound(path)
