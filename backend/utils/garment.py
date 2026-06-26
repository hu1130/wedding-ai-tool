"""Garment preprocessing helpers for try-on requests."""
from __future__ import annotations

import os

from PIL import Image, ImageFilter, ImageOps

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - requirements include these in production
    cv2 = None
    np = None


def _build_mask(image: Image.Image) -> Image.Image:
    if cv2 is None or np is None:
        return _fallback_mask(image)

    rgb = image.convert("RGB")
    original_size = rgb.size
    small = ImageOps.contain(rgb, (640, 640), method=Image.Resampling.LANCZOS)
    bgr = cv2.cvtColor(np.array(small), cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    rect = (
        int(width * 0.06),
        int(height * 0.03),
        int(width * 0.88),
        int(height * 0.94),
    )

    grabcut_mask = np.zeros((height, width), np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, grabcut_mask, rect, bgd_model, fgd_model, 6, cv2.GC_INIT_WITH_RECT)

    mask = np.where(
        (grabcut_mask == cv2.GC_FGD) | (grabcut_mask == cv2.GC_PR_FGD),
        255,
        0,
    ).astype("uint8")
    mask = _keep_large_components(mask)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    alpha = Image.fromarray(mask, "L")
    alpha = alpha.resize(original_size, Image.Resampling.LANCZOS)
    return alpha.filter(ImageFilter.GaussianBlur(1.0))


def _fallback_mask(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    corners = [pixels[0, 0], pixels[width - 1, 0], pixels[0, height - 1], pixels[width - 1, height - 1]]
    bg = tuple(sum(pixel[i] for pixel in corners) // len(corners) for i in range(3))
    mask = Image.new("L", rgb.size, 0)
    out = mask.load()
    for y in range(height):
        for x in range(width):
            pixel = pixels[x, y]
            distance = sum(abs(pixel[i] - bg[i]) for i in range(3))
            if distance > 42:
                out[x, y] = 255
    return mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.0))


def _keep_large_components(mask):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return mask

    areas = stats[1:, cv2.CC_STAT_AREA]
    if len(areas) == 0:
        return mask

    largest = int(areas.max())
    min_area = max(largest * 0.12, mask.shape[0] * mask.shape[1] * 0.001)
    keep = np.zeros_like(mask)
    for idx in range(1, count):
        if stats[idx, cv2.CC_STAT_AREA] >= min_area:
            keep[labels == idx] = 255
    return keep


def _mask_bbox(mask: Image.Image) -> tuple[int, int, int, int] | None:
    if np is not None:
        arr = np.array(mask)
        ys, xs = np.where(arr > 24)
        if len(xs) == 0 or len(ys) == 0:
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    return mask.point(lambda value: 255 if value > 24 else 0).getbbox()


def _expand_bbox(
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
    padding_ratio: float,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    width, height = image_size
    pad_x = int((right - left) * padding_ratio)
    pad_y = int((bottom - top) * padding_ratio)
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(width, right + pad_x),
        min(height, bottom + pad_y),
    )


def _save_reference(image: Image.Image, output_path: str) -> None:
    image = image.convert("RGB")
    max_side = 1400
    if max(image.size) > max_side:
        image = ImageOps.contain(image, (max_side, max_side), method=Image.Resampling.LANCZOS)

    pad = max(24, int(min(image.size) * 0.08))
    canvas = Image.new("RGB", (image.width + pad * 2, image.height + pad * 2), (235, 235, 235))
    canvas.paste(image, (pad, pad))
    canvas.save(output_path, "JPEG", quality=95, optimize=True)


def prepare_tryon_garments(garment_image_path: str, output_dir: str) -> tuple[str, str]:
    """Create top and bottom references so full-length gowns are less likely to be shortened."""
    os.makedirs(output_dir, exist_ok=True)
    source = Image.open(garment_image_path).convert("RGB")
    mask = _build_mask(source)
    bbox = _mask_bbox(mask)
    if bbox is None:
        return garment_image_path, garment_image_path

    bbox = _expand_bbox(bbox, source.size, 0.06)
    garment = source.crop(bbox)
    width, height = garment.size
    if width < 20 or height < 20:
        return garment_image_path, garment_image_path

    top_bottom = max(1, min(height, int(height * 0.58)))
    bottom_top = max(0, min(height - 1, int(height * 0.26)))

    top_reference = garment.crop((0, 0, width, top_bottom))
    bottom_reference = garment.crop((0, bottom_top, width, height))

    top_path = os.path.join(output_dir, "garment_top_reference.jpg")
    bottom_path = os.path.join(output_dir, "garment_floor_length_reference.jpg")
    _save_reference(top_reference, top_path)
    _save_reference(bottom_reference, bottom_path)
    return top_path, bottom_path
