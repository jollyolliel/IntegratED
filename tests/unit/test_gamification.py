from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from helpers.gamification import (
    DEFAULT_FACE,
    FACE_CATEGORIES,
    FACE_ITEMS,
    FACE_LAYER_ORDER,
    FACE_REQUIRED_SLOTS,
    FACE_UNLOCK_LEVEL,
    apply_xp,
    compute_level,
    get_face_item_type,
    items_unlocked_between,
    level_name,
    level_progress,
    resolve_face,
)

if TYPE_CHECKING:
    from models import Learner

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("xp, level", [(0, 1), (499, 1), (500, 2), (3_499, 7), (99_999, 7)])
def test_compute_level_clamps_at_seven(xp, level):
    assert compute_level(xp) == level


def test_level_name_clamps_out_of_range_levels():
    assert level_name(1) == "Rookie"
    assert level_name(99) == "Legend"


def test_apply_xp_uses_starting_level_multiplier_and_reports_level_up():
    learner = cast("Learner", type("Learner", (), {"xp": 490})())

    earned, new_level = apply_xp(learner, 10)

    assert earned == 10
    assert learner.xp == 500
    assert new_level == 2


def test_level_progress_reports_the_bar_and_what_is_next():
    progress = level_progress(620)

    assert (progress["level"], progress["xp_in_level"], progress["xp_left"]) == (2, 120, 380)
    assert progress["next_level"] == 3 and progress["next_name"] == "Navigator"


def test_level_progress_stays_full_at_the_top():
    progress = level_progress(99_999)

    assert progress["at_top"] is True and progress["percent"] == 100 and progress["next_name"] == ""


def test_a_level_up_unlocks_exactly_the_items_of_the_levels_crossed():
    unlocked = {item["id"] for item in items_unlocked_between(1, 3)}

    expected = {item_id for item_id, level in FACE_UNLOCK_LEVEL.items() if 1 < level <= 3}
    assert unlocked == expected and unlocked


def test_resolve_face_keeps_only_items_that_fit_their_slot():
    face = resolve_face({"species": "crown", "hair": "face_hair_bun", "top": None, "eyes": None})

    assert face["species"] == DEFAULT_FACE["species"]   # an old-catalogue id is ignored
    assert face["hair"] == "face_hair_bun"
    assert face["top"] == DEFAULT_FACE["top"]           # a required slot is never empty
    assert face["eyes"] is None                        # an optional slot may be taken off
    assert resolve_face(None) == DEFAULT_FACE


# ── Face System wardrobe ─────────────────────────────────────────────────────

AVATAR_ART = Path(__file__).resolve().parents[2] / "static" / "svg" / "avatar"


def test_the_wardrobe_offers_body_clothes_and_an_outfit_colour():
    assert {"top", "bottom", "shoes", "colour"} <= set(FACE_CATEGORIES)


def test_every_drawn_slot_has_a_layer_and_colour_is_not_one():
    assert set(FACE_LAYER_ORDER) == set(FACE_CATEGORIES) - {"colour"}
    assert FACE_LAYER_ORDER[0] == "species"


def test_every_required_slot_starts_on_a_free_item_of_its_own_type():
    for slot in FACE_REQUIRED_SLOTS:
        item_id = DEFAULT_FACE[slot]
        assert item_id is not None
        assert get_face_item_type(item_id) == slot
        assert FACE_UNLOCK_LEVEL.get(item_id, 1) == 1


@pytest.mark.parametrize(
    "item_id",
    [item["id"] for cat, items in FACE_ITEMS.items() if cat != "colour" for item in items],
)
def test_every_drawn_item_has_full_body_art_to_stack(item_id):
    """Every layer shares one 200×300 box, and the page draws it through <use href="…#art">."""
    svg = (AVATAR_ART / f"{item_id}.svg").read_text(encoding="utf-8")

    assert 'viewBox="0 0 200 300"' in svg
    assert 'id="art"' in svg
