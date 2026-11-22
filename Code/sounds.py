"""Sounds loaded once: one pygame Sound per (file, volume), shared by every body that plays it.

A Sound's volume belongs to the Sound, so the same file at two volumes is two entries.
Dialogue voice lines keep their own loader (dialogue/voice.py): each line is its own file.
"""
import pygame

_cache = {}


def get(path, volume=1.0):
    key = (path, volume)
    sound = _cache.get(key)
    if sound is None:
        sound = pygame.mixer.Sound(path)
        sound.set_volume(volume)
        _cache[key] = sound
    return sound
