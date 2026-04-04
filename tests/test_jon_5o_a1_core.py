from __future__ import annotations

import sys
from pathlib import Path


JON_5O_A1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "jon-5o-a1"
if str(JON_5O_A1_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5O_A1_ROOT))

from core_bot import BONUS_ASSAULT_QUOTA, INITIAL_ASSAULT_QUOTA, CoreBot


class _StubController:
    def __init__(
        self,
        *,
        titanium: int,
    ) -> None:
        self._titanium = titanium

    def get_global_resources(self) -> tuple[int, int]:
        return (self._titanium, 0)


def test_initial_two_assault_bots_do_not_wait_for_connected_lanes():
    bot = CoreBot()
    bot.builder_counter = 4

    quota = bot._current_assault_quota(_StubController(titanium=60))

    assert quota == INITIAL_ASSAULT_QUOTA


def test_third_assault_bot_stays_locked_below_titanium_threshold():
    bot = CoreBot()
    bot.builder_counter = 7

    quota = bot._current_assault_quota(_StubController(titanium=89))

    assert quota == INITIAL_ASSAULT_QUOTA


def test_third_assault_bot_unlocks_at_titanium_threshold():
    bot = CoreBot()
    bot.builder_counter = 7

    quota = bot._current_assault_quota(_StubController(titanium=90))

    assert quota == BONUS_ASSAULT_QUOTA
