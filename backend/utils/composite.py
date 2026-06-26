"""Lightweight foreground extraction and scene compositing."""
from __future__ import annotations

import os
from collections import deque
from statistics import median

from PIL import Image, ImageFilter, ImageOps

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - optional local quality upgrade
    cv2 = None
    np = None


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _estimate_background_color(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    samples: list[tuple[int, int, int]] = []
    step = max(1, min(width, height) // 80)

    for x in range(0, width, step):
        samples.append(pixels[x, 0])
        samples.append(pixels[x, height - 1])
    for y in range(0, height, step):
        samples.append(pixels[0, y])
        samples.append(pixels[width - 1, y])

    return (
        int(median(pixel[0] for pixel in samples)),
        int(median(pixel[1] for pixel in samples)),
        int(median(pixel[2] for pixel in samples)),
    )


def _build_foreground_mask(image: Image.Image) -> Image.Image:
    if cv2 is not None and np is not None:
        return _build_grabcut_mask(image)
    return _build_color_flood_mask(image)


def _build_grabcut_mask(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    original_size = rgb.size
    small = ImageOps.contain(rgb, (520, 520), method=Image.Resampling.LANCZOS)
    bgr = cv2.cvtColor(np.array(small), cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]

    # The try-on model keeps the subject centered. A broad rectangle lets
    # GrabCut separate white dresses from light studio backgrounds better than
    # color thresholding can.
    rect = (
        int(width * 0.10),
        int(height * 0.03),
        int(width * 0.80),
        int(height * 0.95),
    )
    grabcut_mask = np.zeros((height, width), np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, grabcut_mask, rect, bgd_model, fgd_model, 8, cv2.GC_INIT_WITH_RECT)

    mask = np.where(
        (grabcut_mask == cv2.GC_FGD) | (grabcut_mask == cv2.GC_PR_FGD),
        255,
        0,
    ).astype("uint8")
    mask = _keep_center_components(mask)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    alpha = Image.fromarray(mask, "L")
    alpha = alpha.resize(original_size, Image.Resampling.LANCZOS)
    return alpha.filter(ImageFilter.GaussianBlur(1.4))


def _keep_center_components(mask):
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    keep = np.zeros_like(mask)
    height, width = mask.shape
    min_area = height * width * 0.001

    for idx in range(1, count):
        area = stats[idx, cv2.CC_STAT_AREA]
        center_x, _ = centroids[idx]
        if area >= min_area and width * 0.08 <= center_x <= width * 0.92:
            keep[labels == idx] = 255

    return keep


def _build_color_flood_mask(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    original_size = rgb.size
    max_side = 760

    if max(original_size) > max_side:
        rgb = ImageOps.contain(rgb, (max_side, max_side), method=Image.Resampling.LANCZOS)

    width, height = rgb.size
    pixels = rgb.load()
    bg_color = _estimate_background_color(rgb)
    tolerance = 58

    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        idx = y * width + x
        if visited[idx]:
            return
        if _color_distance(pixels[x, y], bg_color) <= tolerance:
            visited[idx] = 1
            queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                enqueue(nx, ny)

    mask = Image.new("L", (width, height), 255)
    mask_pixels = mask.load()
    for y in range(height):
        row = y * width
        for x in range(width):
            if visited[row + x]:
                mask_pixels[x, y] = 0

    mask = mask.filter(ImageFilter.MinFilter(7))
    mask = mask.filter(ImageFilter.MaxFilter(5))
    mask = mask.filter(ImageFilter.GaussianBlur(1.5))

    if mask.size != original_size:
        mask = mask.resize(original_size, Image.Resampling.LANCZOS)

    return mask


def _cover_resize(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_width, target_height = target_size
    source_width, source_height = image.size
    scale = max(target_width / source_width, target_height / source_height)
    resized = image.resize(
        (int(source_width * scale), int(source_height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - target_width) // 2)
    top = max(0, (resized.height - target_height) // 2)
    return resized.crop((left, top, left + target_width, top + target_height))


def composite_subject_on_background(
    subject_image_path: str,
    background_image_path: str,
    output_dir: str,
) -> str:
    subject = Image.open(subject_image_path).convert("RGBA")
    background = Image.open(background_image_path).convert("RGB")
    background = _cover_resize(background, subject.size).convert("RGBA")

    mask = _build_foreground_mask(subject)
    shadow = Image.new("RGBA", subject.size, (0, 0, 0, 0))
    shadow_alpha = mask.filter(ImageFilter.GaussianBlur(18)).point(lambda value: int(value * 0.22))
    shadow.putalpha(shadow_alpha)

    shadow_layer = Image.new("RGBA", subject.size, (0, 0, 0, 0))
    shadow_layer.alpha_composite(shadow, (0, max(8, subject.height // 90)))
    background.alpha_composite(shadow_layer)
    background.paste(subject, (0, 0), mask)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "stable_composite.jpg")
    background.convert("RGB").save(output_path, "JPEG", quality=94, optimize=True)
    return output_path
