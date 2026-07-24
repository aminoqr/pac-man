"""Headless tests for the UI: the platform-neutral shell + key mapping.

The screen FSM, menu navigation, pause flow, and the end-of-game
name-entry -> highscore-save path all live in ``pacman.ui.shell`` with
zero graphics-library dependency, so they are driven directly with
abstract :class:`Action` values -- no window, no MLX (the MLX C loop
cannot run headless). A separate check covers the pure keysym ->
action/char translation used by the MLX front-end.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from pacman.highscore.store import HighscoreTable
from pacman.maze.adapter import Direction
from pacman.ui.shell import MS_PER_TICK, Action, GameShell, Screen
from tests.engine_helpers import make_test_config

if TYPE_CHECKING:  # annotation only -- keep the mlx import lazy at runtime
    from pacman.ui.app import MlxApp


def _shell(tmp_path: Path) -> GameShell:
    """A shell whose highscores write to a temp file."""
    hs_path = str(tmp_path / "hs.json")
    return GameShell(make_test_config(highscore_filename=hs_path))


def _clear_banners(shell: GameShell) -> None:
    """Run out every queued interstitial so play can start ticking."""
    for _ in range(50):
        if shell.banner_text is None:
            return
        shell.advance(1000.0)
    raise AssertionError("banners never cleared")


def _screen(shell: GameShell) -> Screen:
    """Read the current screen as a plain Screen.

    Routing through a function widens mypy's literal narrowing, so
    successive ``is Screen.X`` assertions on the same shell pass under
    ``mypy --strict`` without false "non-overlapping" errors.
    """
    return shell.screen


def test_main_menu_navigation_and_info_screens(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    assert _screen(shell) is Screen.MAIN_MENU

    # Wrap-around navigation: Up from the top lands on the last item.
    shell.dispatch(Action.UP)
    assert shell.menu_index == 3
    shell.dispatch(Action.DOWN)
    assert shell.menu_index == 0

    # Instructions (index 2) and Highscores (index 1) round-trip.
    shell.menu_index = 2
    shell.dispatch(Action.CONFIRM)
    assert _screen(shell) is Screen.INSTRUCTIONS
    shell.dispatch(Action.BACK)
    assert _screen(shell) is Screen.MAIN_MENU

    shell.menu_index = 1
    shell.dispatch(Action.CONFIRM)
    assert _screen(shell) is Screen.HIGHSCORES
    shell.dispatch(Action.CONFIRM)
    assert _screen(shell) is Screen.MAIN_MENU


def test_exit_item_and_quit_stop_the_loop(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    shell.menu_index = 3  # Exit
    shell.dispatch(Action.CONFIRM)
    assert not shell.running

    other = _shell(tmp_path)
    other.dispatch(Action.QUIT)  # window close, from any screen
    assert not other.running


def test_start_pause_resume_and_return_to_menu(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    shell.menu_index = 0  # Start Game
    shell.dispatch(Action.CONFIRM)
    assert _screen(shell) is Screen.PLAYING
    assert shell.session is not None

    # Steering buffers a direction; cheats toggle through dispatch.
    shell.dispatch(Action.LEFT)
    assert shell.session.state.buffered_direction is Direction.WEST
    shell.dispatch(Action.CHEAT_INVINCIBLE)
    assert shell.session.state.cheats.invincible
    shell.dispatch(Action.CHEAT_LIFE)
    assert shell.session.lives == 4

    # A new game opens on its interstitials, which hold the simulation
    # still until they expire.
    assert shell.banner_text is not None
    before = shell.session.state.tick_count
    shell.advance(MS_PER_TICK * 2)
    assert shell.session.state.tick_count == before, "frozen by the banner"
    _clear_banners(shell)

    # Only PLAYING advances the simulation.
    before = shell.session.state.tick_count
    shell.advance(MS_PER_TICK * 2)
    assert shell.session.state.tick_count == before + 2

    # Pause freezes the sim.
    shell.dispatch(Action.PAUSE)
    assert _screen(shell) is Screen.PAUSED
    paused_tick = shell.session.state.tick_count
    shell.advance(MS_PER_TICK * 3)
    assert shell.session.state.tick_count == paused_tick

    # Resume via the pause menu's first item.
    shell.pause_index = 0
    shell.dispatch(Action.CONFIRM)
    assert _screen(shell) is Screen.PLAYING

    # Pause again, choose "Return to Main Menu": the game is dropped.
    shell.dispatch(Action.BACK)
    shell.pause_index = 1
    shell.dispatch(Action.CONFIRM)
    assert _screen(shell) is Screen.MAIN_MENU
    assert shell.session is None


def test_victory_name_entry_persists_a_highscore(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    shell.menu_index = 0
    shell.dispatch(Action.CONFIRM)  # Start Game
    # Skip-cheat all the way to a full-game victory.
    for _ in range(20):
        shell.dispatch(Action.CHEAT_SKIP)
        if _screen(shell) is Screen.NAME_ENTRY:
            break
    assert _screen(shell) is Screen.NAME_ENTRY
    assert shell.final_won  # reached VICTORY, not GAME_OVER

    # Type a name; a filtered-out symbol is ignored, cap respected.
    for char in "Ada!":
        shell.dispatch(None, char)
    assert shell.name_buffer == "Ada"  # '!' dropped
    shell.dispatch(Action.BACKSPACE)
    assert shell.name_buffer == "Ad"
    shell.dispatch(None, "a")
    shell.dispatch(Action.CONFIRM)  # confirm + save

    assert _screen(shell) is Screen.MAIN_MENU
    assert shell.session is None
    reloaded = HighscoreTable.load(shell.highscore_path)
    assert any(e.name == "Ada" for e in reloaded.entries)


def test_name_entry_respects_the_ten_char_cap(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    shell.menu_index = 0
    shell.dispatch(Action.CONFIRM)
    shell._end_game()  # jump to name entry directly
    for char in "abcdefghijklmnop":  # 16 chars
        shell.dispatch(None, char)
    assert shell.name_buffer == "abcdefghij"  # capped at 10


def test_zero_lives_config_goes_straight_to_name_entry(
    tmp_path: Path,
) -> None:
    hs_path = str(tmp_path / "hs.json")
    shell = GameShell(make_test_config(lives=0, highscore_filename=hs_path))
    shell.menu_index = 0
    shell.dispatch(Action.CONFIRM)  # Start Game
    assert _screen(shell) is Screen.NAME_ENTRY  # born game-over
    assert not shell.final_won


def test_keysym_translation_maps_navigation_and_typing() -> None:
    from pacman.ui.app import keysym_to_action

    assert keysym_to_action(0xFF52) == (Action.UP, "")       # Up arrow
    assert keysym_to_action(0xFF1B) == (Action.BACK, "")     # Escape
    assert keysym_to_action(0xFFBE) == (Action.CHEAT_INVINCIBLE, "")  # F1
    # WASD are both navigation and printable; the shell picks per screen.
    assert keysym_to_action(0x77) == (Action.UP, "w")
    assert keysym_to_action(0x20) == (Action.CONFIRM, " ")   # Space
    assert keysym_to_action(0x35) == (None, "5")             # digit 5
    assert keysym_to_action(0x41) == (None, "A")             # uppercase A


BLANK_W, BLANK_H = 400, 200


def _blank_app() -> "MlxApp":
    """An MlxApp with a bare pixel buffer and no window.

    The window is sized from the display at runtime, so drawing clips
    against the instance's own width/height -- set them to match the
    buffer handed over here and nothing is written past its end.
    """
    from pacman.ui import app as appmod

    app = appmod.MlxApp.__new__(appmod.MlxApp)
    app.width = BLANK_W
    app.height = BLANK_H
    app.size_line = BLANK_W * 4
    app.buffer = memoryview(bytearray(BLANK_W * BLANK_H * 4))
    return app


def test_direction_arrow_rasterises_a_triangle() -> None:
    """The heading/queued markers have no polygon primitive behind them,
    so verify the actual pixels: each step back from the apex widens the
    slab by one pixel either side."""
    from pacman.ui import app as appmod

    app = _blank_app()
    buffer = app.buffer
    assert buffer is not None

    def lit(row: int) -> int:
        return sum(
            1 for x in range(BLANK_W)
            if buffer[row * app.size_line + x * 4 + 2]  # red channel
        )

    app._arrow(100, 40, Direction.NORTH, 4, appmod.PLAYER)
    assert [lit(40 + i) for i in range(4)] == [1, 3, 5, 7]
    assert lit(39) == 0  # nothing spills past the apex


def test_queued_turn_is_drawn_only_while_an_input_is_pending() -> None:
    """A buffered 90-degree turn shows a marker in its own colour, so a
    press that cannot fire until the next tile center is still visibly
    acknowledged. Nothing is drawn once the buffer clears."""
    from pacman.ui import app as appmod
    from tests.engine_helpers import make_state
    from tests.mazes import PLAZA_3x3

    state = make_state(PLAZA_3x3, player=(1, 1))
    state.player_direction = Direction.EAST

    def intent_pixels() -> int:
        app = _blank_app()
        app._draw_player_heading(state, 1.0, 1.0, 48, 0, 0, 16)
        buffer = app.buffer
        assert buffer is not None
        packed = bytes((INTENT_B, INTENT_G, INTENT_R, 255))
        return bytes(buffer).count(packed)

    INTENT_R, INTENT_G, INTENT_B = appmod.INTENT
    assert intent_pixels() == 0  # nothing queued

    state.buffer_input(Direction.NORTH)
    assert intent_pixels() > 0  # pending turn is shown

    state.buffer_input(Direction.EAST)  # same as facing -> not a turn
    assert intent_pixels() == 0
