"""Clothing type configuration.

Wedding remains the primary production mode. Other clothing types are enabled
as domain-ready extensions so the API and storage model do not need another
schema change later.
"""

from __future__ import annotations

from dataclasses import dataclass


WEDDING_GOWN = "wedding_gown"


@dataclass(frozen=True)
class ClothingTypeConfig:
    value: str
    label: str
    garment_name: str
    style_prompt: str
    negative_prompt: str
    primary: bool = False


CLOTHING_TYPE_CONFIGS: dict[str, ClothingTypeConfig] = {
    WEDDING_GOWN: ClothingTypeConfig(
        value=WEDDING_GOWN,
        label="婚纱",
        garment_name="wedding gown",
        style_prompt="preserve the exact wedding gown silhouette, neckline, waistline, train, lace or satin texture",
        negative_prompt="short skirt, casual white dress, evening dress, missing train, cropped hem, changed gown design",
        primary=True,
    ),
    "evening_dress": ClothingTypeConfig(
        value="evening_dress",
        label="礼服裙",
        garment_name="evening dress",
        style_prompt="preserve the evening dress cut, fabric texture, neckline, waist shape, sleeve shape and hem length",
        negative_prompt="wedding veil, bridal train, casual dress, changed dress color, distorted hem, wrong neckline",
    ),
    "suit": ClothingTypeConfig(
        value="suit",
        label="西装",
        garment_name="tailored suit",
        style_prompt="preserve the suit jacket structure, lapels, shoulder line, trousers, buttons and fabric texture",
        negative_prompt="dress, skirt, wedding gown, wrong lapel, missing trousers, distorted buttons, casual hoodie",
    ),
    "hanfu": ClothingTypeConfig(
        value="hanfu",
        label="汉服",
        garment_name="hanfu outfit",
        style_prompt="preserve the hanfu layers, collar crossing, sleeves, sash, drape and traditional fabric details",
        negative_prompt="wedding gown, modern suit, missing sleeves, wrong collar, distorted sash, simplified robe",
    ),
    "cheongsam": ClothingTypeConfig(
        value="cheongsam",
        label="旗袍",
        garment_name="cheongsam",
        style_prompt="preserve the cheongsam collar, side closure, fitted silhouette, slit position and fabric pattern",
        negative_prompt="wedding gown, loose robe, wrong collar, changed slit, distorted pattern, casual dress",
    ),
    "casual_outfit": ClothingTypeConfig(
        value="casual_outfit",
        label="日常穿搭",
        garment_name="casual outfit",
        style_prompt="preserve the outfit pieces, fabric, color, proportions, sleeves, hem and everyday styling",
        negative_prompt="wedding gown, formal gown, suit, changed clothing category, distorted sleeve, wrong color",
    ),
}


SUPPORTED_CLOTHING_TYPES = frozenset(CLOTHING_TYPE_CONFIGS)


def get_clothing_type_config(value: str | None) -> ClothingTypeConfig:
    normalized = (value or WEDDING_GOWN).strip()
    return CLOTHING_TYPE_CONFIGS.get(normalized, CLOTHING_TYPE_CONFIGS[WEDDING_GOWN])


def is_wedding_clothing(value: str | None) -> bool:
    return get_clothing_type_config(value).value == WEDDING_GOWN
