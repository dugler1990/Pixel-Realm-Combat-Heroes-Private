import os

import pygame


class ImageCache:
    cache = {}
    _folder_cache = {}

    @staticmethod
    def _normalize_path(path):
        return os.path.abspath(os.path.normpath(path))

    @staticmethod
    def _scale_key(scale):
        if scale is None:
            return None
        if isinstance(scale, (list, tuple)):
            return tuple(scale)
        return scale

    @staticmethod
    def folder_cache_key(folder, scale=None):
        return (ImageCache._normalize_path(folder), ImageCache._scale_key(scale))

    @staticmethod
    def load_image(path):
        """Load an image from a path, using the cache to avoid reloading from disk."""
        norm = ImageCache._normalize_path(path)
        if norm not in ImageCache.cache:
            ImageCache.cache[norm] = pygame.image.load(norm).convert_alpha()
        return ImageCache.cache[norm]

    @staticmethod
    def load_folder(folder):
        """Load all images in a folder, treating them as a sequence of frames."""
        images = []
        norm = ImageCache._normalize_path(folder)
        for filename in sorted(os.listdir(norm)):
            full_path = os.path.join(norm, filename)
            images.append(ImageCache.load_image(full_path))
        return images
