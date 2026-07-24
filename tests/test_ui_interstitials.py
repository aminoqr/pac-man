"""Interstitial banners: the arcade's beat before anything moves.

The real game never drops you straight into play -- it holds the board
still and tells you what is happening (GET READY! / READY! / LEVEL
CLEARED!). These live in the shell, so they are drivable headlessly:
while a banner is up, ``advance`` must not tick the session at all.
"""

from pacman.ui.shell import (
    GAME_START_TEXT,
    LEVEL_CLEARED_TEXT,
    MS_PER_TICK,
    READY_TEXT,
    Action,
    GameShell,
)
from tests.engine_helpers import make_test_config


def _shell() -> GameShell:
    shell = GameShell(make_test_config())
    shell.start_new_game()
    return shell


def test_a_new_game_opens_on_its_interstitials() -> None:
    shell = _shell()
    assert shell.banner_text == GAME_START_TEXT


def test_the_simulation_is_frozen_while_a_banner_shows() -> None:
    shell = _shell()
    assert shell.session is not None
    before = shell.session.state.tick_count
    shell.advance(MS_PER_TICK * 5)
    assert shell.session.state.tick_count == before


def test_banners_play_in_order_then_hand_over_to_play() -> None:
    shell = _shell()
    assert shell.session is not None
    shell.advance(2000)  # GET READY! elapses
    assert shell.banner_text == READY_TEXT
    shell.advance(2500)  # READY! elapses
    assert shell.banner_text is None
    before = shell.session.state.tick_count
    shell.advance(MS_PER_TICK * 3)
    assert shell.session.state.tick_count > before  # play resumed


def test_clearing_a_level_announces_it_then_gets_ready_again() -> None:
    shell = _shell()
    assert shell.session is not None
    shell.advance(6000)  # run out the opening banners
    assert shell.banner_text is None

    shell.session.advance_level()  # as the level-skip cheat does
    shell.advance(MS_PER_TICK)  # the next tick notices the new level
    assert shell.banner_text == LEVEL_CLEARED_TEXT
    shell.advance(2000)
    assert shell.banner_text == READY_TEXT


def test_a_banner_does_not_bank_up_catch_up_ticks() -> None:
    """Time spent reading a banner must not fast-forward the game the
    moment it clears -- the accumulator is reset, not paused."""
    shell = _shell()
    assert shell.session is not None
    shell.advance(9000)  # a long stall while banners run out
    before = shell.session.state.tick_count
    shell.advance(MS_PER_TICK)  # exactly one tick's worth of time
    assert shell.session.state.tick_count == before + 1


def test_pausing_during_a_banner_is_still_possible() -> None:
    """The pause menu must remain reachable mid-interstitial."""
    shell = _shell()
    shell.dispatch(Action.PAUSE)
    from pacman.ui.shell import Screen
    assert shell.screen is Screen.PAUSED
