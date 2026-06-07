import os

import pygame


class ImageCache:
    cache = {}
    _folder_cache = {}
    _scaled_cache = {}

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
    def load_scaled(path, size):
        """Load and scale an image, caching by normalized path and target size."""
        scale = ImageCache._scale_key(size)
        if scale is None:
            raise ValueError("size is required for load_scaled")
        key = (ImageCache._normalize_path(path), scale)
        cached = ImageCache._scaled_cache.get(key)
        if cached is None:
            base = ImageCache.load_image(path)
            cached = pygame.transform.scale(base, tuple(scale))
            ImageCache._scaled_cache[key] = cached
        return cached

    @staticmethod
    def load_folder(folder):
        """Load all images in a folder, treating them as a sequence of frames."""
        images = []
        norm = ImageCache._normalize_path(folder)
        for filename in sorted(os.listdir(norm)):
            full_path = os.path.join(norm, filename)
            images.append(ImageCache.load_image(full_path))
        return images
