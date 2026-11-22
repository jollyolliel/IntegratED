"""The Face System: a full-body avatar stacked from transparent SVG layers. Every layer shares one
200x300 box in static/svg/avatar/ and wraps its drawing in <g id="art">, so the page can stack
them with <use> and recolour the outfit through CSS variables. Draw order is FACE_LAYER_ORDER;
`colour` is not drawn, it tints the outfit layers."""

from typing import TypedDict

FACE_LAYER_ORDER = ['species', 'shoes', 'bottom', 'top', 'hair', 'eyes', 'mouth', 'extra']

FACE_ITEMS = {
    'species': [
        {'id': 'face_species_cat',     'label': 'Cat'},
        {'id': 'face_species_bear',    'label': 'Bear'},
        {'id': 'face_species_fox',     'label': 'Fox'},
        {'id': 'face_species_rabbit',  'label': 'Rabbit'},
        {'id': 'face_species_frog',    'label': 'Frog'},
        {'id': 'face_species_dog',     'label': 'Dog'},
        {'id': 'face_species_penguin', 'label': 'Penguin'},
        {'id': 'face_species_lion',    'label': 'Lion'},
    ],
    'eyes': [
        {'id': 'face_eyes_happy',     'label': 'Happy'},
        {'id': 'face_eyes_sparkle',   'label': 'Sparkle'},
        {'id': 'face_eyes_surprised', 'label': 'Surprised'},
        {'id': 'face_eyes_sleepy',    'label': 'Sleepy'},
        {'id': 'face_eyes_star',      'label': 'Star'},
        {'id': 'face_eyes_cool',      'label': 'Cool'},
        {'id': 'face_eyes_wink',      'label': 'Wink'},
        {'id': 'face_eyes_heart',     'label': 'Hearts'},
    ],
    'mouth': [
        {'id': 'face_mouth_smile',    'label': 'Smile'},
        {'id': 'face_mouth_grin',     'label': 'Grin'},
        {'id': 'face_mouth_smirk',    'label': 'Smirk'},
        {'id': 'face_mouth_open',     'label': 'Open'},
        {'id': 'face_mouth_tongue',   'label': 'Tongue'},
        {'id': 'face_mouth_cat',      'label': 'Kitty'},
        {'id': 'face_mouth_straight', 'label': 'Straight'},
    ],
    'hair': [
        {'id': 'face_hair_short',    'label': 'Short'},
        {'id': 'face_hair_long',     'label': 'Long'},
        {'id': 'face_hair_ponytail', 'label': 'Ponytail'},
        {'id': 'face_hair_bun',      'label': 'Bun'},
        {'id': 'face_hair_curly',    'label': 'Curly'},
        {'id': 'face_hair_spiky',    'label': 'Spiky'},
        {'id': 'face_hair_afro',     'label': 'Afro'},
        {'id': 'face_hair_hijab',    'label': 'Hijab'},
        {'id': 'face_hair_braids',   'label': 'Braids'},
        {'id': 'face_hair_bangs',    'label': 'Bangs'},
    ],
    'extra': [
        {'id': 'face_extra_bow',        'label': 'Bow'},
        {'id': 'face_extra_cap',        'label': 'Cap'},
        {'id': 'face_extra_glasses',    'label': 'Glasses'},
        {'id': 'face_extra_scarf',      'label': 'Scarf'},
        {'id': 'face_extra_crown',      'label': 'Crown'},
        {'id': 'face_extra_beanie',     'label': 'Beanie'},
        {'id': 'face_extra_cat_ears',   'label': 'Cat Ears'},
        {'id': 'face_extra_headphones', 'label': 'Headphones'},
        {'id': 'face_extra_flower',     'label': 'Flower'},
        {'id': 'face_extra_halo',       'label': 'Halo'},
        {'id': 'face_extra_horns',      'label': 'Horns'},
    ],
    'top': [
        {'id': 'avatar_top_hoodie',  'label': 'Hoodie'},
        {'id': 'avatar_top_tshirt',  'label': 'T-shirt'},
        {'id': 'avatar_top_dress',   'label': 'Dress'},
        {'id': 'avatar_top_jacket',  'label': 'Jacket'},
        {'id': 'avatar_top_sweater', 'label': 'Sweater'},
    ],
    'bottom': [
        {'id': 'avatar_bottom_jeans',   'label': 'Jeans'},
        {'id': 'avatar_bottom_shorts',  'label': 'Shorts'},
        {'id': 'avatar_bottom_skirt',   'label': 'Skirt'},
        {'id': 'avatar_bottom_joggers', 'label': 'Joggers'},
    ],
    'shoes': [
        {'id': 'avatar_shoes_sneakers',  'label': 'Sneakers'},
        {'id': 'avatar_shoes_sandals',   'label': 'Sandals'},
        {'id': 'avatar_shoes_boots',     'label': 'Boots'},
        {'id': 'avatar_shoes_rainboots', 'label': 'Rain boots'},
    ],
    'colour': [
        {'id': 'avatar_colour_sky',    'label': 'Sky'},
        {'id': 'avatar_colour_pink',   'label': 'Pink'},
        {'id': 'avatar_colour_green',  'label': 'Green'},
        {'id': 'avatar_colour_amber',  'label': 'Sun'},
        {'id': 'avatar_colour_red',    'label': 'Red'},
        {'id': 'avatar_colour_orange', 'label': 'Orange'},
        {'id': 'avatar_colour_indigo', 'label': 'Night'},
        {'id': 'avatar_colour_purple', 'label': 'Purple'},
    ],
}

FACE_CATEGORIES = list(FACE_ITEMS.keys())

DEFAULT_FACE = {
    'species': 'face_species_cat',
    'eyes':    'face_eyes_happy',
    'mouth':   'face_mouth_smile',
    'hair':    None,
    'extra':   None,
    'top':     'avatar_top_hoodie',
    'bottom':  'avatar_bottom_jeans',
    'shoes':   'avatar_shoes_sneakers',
    'colour':  'avatar_colour_sky',
}

#: Slots that are never empty: picking the worn item again keeps it on.
FACE_REQUIRED_SLOTS = frozenset({'species', 'top', 'bottom', 'shoes', 'colour'})

# Item IDs that require a minimum level to unlock. Unlisted = available at level 1.
FACE_UNLOCK_LEVEL = {
    'face_eyes_star':         2,
    'face_eyes_cool':         2,
    'face_eyes_wink':         2,
    'face_mouth_cat':         2,
    'face_hair_bun':          2,
    'face_hair_curly':        2,
    'face_hair_spiky':        2,
    'face_extra_cap':         2,
    'avatar_top_jacket':      2,
    'avatar_bottom_joggers':  2,
    'avatar_shoes_boots':     2,
    'avatar_colour_red':      2,
    'avatar_colour_orange':   2,
    'face_species_penguin':   3,
    'face_eyes_heart':        3,
    'face_hair_afro':         3,
    'face_hair_hijab':        3,
    'face_hair_braids':       3,
    'face_extra_glasses':     3,
    'face_extra_scarf':       3,
    'avatar_top_sweater':     3,
    'avatar_shoes_rainboots': 3,
    'avatar_colour_indigo':   3,
    'face_species_lion':      4,
    'face_hair_bangs':        4,
    'face_extra_cat_ears':    4,
    'face_extra_headphones':  4,
    'face_extra_flower':      4,
    'avatar_colour_purple':   4,
    'face_extra_beanie':      5,
    'face_extra_crown':       5,
    'face_extra_halo':        6,
    'face_extra_horns':       7,
}

_FACE_ID_TO_TYPE = {
    item['id']: cat
    for cat, items in FACE_ITEMS.items()
    for item in items
}

FACE_ID_SET = set(_FACE_ID_TO_TYPE.keys())


#: A learner's worn items, one per FACE_CATEGORIES slot (None = an empty optional slot).
type FaceEquipped = dict[str, str | None]


def resolve_face(stored: object) -> FaceEquipped:
    """What a learner wears: `DEFAULT_FACE`, with each stored item that fits its slot laid over it.

    Anything stored that isn't a Face System item for that slot — another catalogue's ids, or a
    stale value — is ignored, so every reader (the dashboard, the equip response) sees the same face.

    Args:
        stored (object): `Learner.equipped_items`, possibly None or malformed.

    Returns:
        FaceEquipped: Every slot, filled.
    """
    face: FaceEquipped = dict(DEFAULT_FACE)
    if not isinstance(stored, dict):
        return face
    for slot in DEFAULT_FACE:
        value = stored.get(slot)
        if value is None and slot not in FACE_REQUIRED_SLOTS and slot in stored:
            face[slot] = None
        elif isinstance(value, str) and _FACE_ID_TO_TYPE.get(value) == slot:
            face[slot] = value
    return face


def get_face_item_type(item_id: str) -> str | None:
    """Return the Face System slot (a FACE_CATEGORIES key) for an item id.

    Args:
        item_id (str): Face item id.

    Returns:
        str | None: The slot, or None if unknown.
    """
    return _FACE_ID_TO_TYPE.get(item_id)


class UnlockedItem(TypedDict):
    """A wardrobe item a level-up made available."""

    id: str
    type: str
    label: str


def items_unlocked_between(old_level: int, new_level: int) -> list[UnlockedItem]:
    """The wardrobe items a learner gains by climbing from ``old_level`` to ``new_level``.

    Args:
        old_level (int): The level before.
        new_level (int): The level after.

    Returns:
        list[UnlockedItem]: Every item whose unlock level is above the old level and at most the
            new one, in wardrobe order.
    """
    return [
        UnlockedItem(id=item["id"], type=category, label=item["label"])
        for category, items in FACE_ITEMS.items()
        for item in items
        if old_level < FACE_UNLOCK_LEVEL.get(item["id"], 1) <= new_level
    ]
