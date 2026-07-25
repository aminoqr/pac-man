"""Platform-neutral game shell: the screen FSM and input handling.

This module owns everything about *what* the UI does -- the screen
state machine (subject VI.8), menu navigation, the pause flow, and the
game-over/victory name entry -- with **zero** dependency on any graphics
library. Input arrives as abstract :class:`Action` values (plus a typed
character for name entry), so the same shell is driven identically by
the MLX front-end (``app.py``) and by the headless tests. Rendering is
someone else's job: a renderer reads this object's public state.

Keeping the graphics library out of here is what lets the whole UI be
unit-tested without opening a window (the MLX C loop cannot run
headless), the same separation the engine already enjoys.
"""

import logging
from enum import Enum, auto

from pacman.config.loader import Config
from pacman.game.engine import ENGINE_TICKS_PER_SECOND
from pacman.game.session import GameSession, SessionStatus
from pacman.highscore.store import MAX_NAME_LENGTH, HighscoreTable
from pacman.maze.adapter import Direction

logger = logging.getLogger(__name__)

# Float: 1000/60 is not a whole number, and truncating it would run the
# simulation measurably fast against the wall clock.
MS_PER_TICK = 1000 / ENGINE_TICKS_PER_SECOND

# Tiles covered per engine tick. Movement is continuous (the engine
# crosses a tile over a whole number of ticks), so these set real speed
# rather than a stutter pattern; the engine rounds 1/speed to that tick
# count, so any value is smooth.
#
# The player covers a tile every 12 ticks = 5 tiles/sec, calm to
# control, with a tile center -- i.e. a turn opportunity -- every 200 ms.
PLAYER_SPEED = 1 / 12

# Ghosts take 16 ticks a tile = 3.75 tiles/sec, i.e. 75% of the player.
#
# The arcade's own level-1 numbers are 80% of base speed for Pac-Man and
# 75% for the ghosts -- so there they run at ~94% of his pace. Matching
# that number here would play HARDER than the original, not truer to it:
# arcade ghosts navigate by wall-blind straight-line distance and lose
# ground every time a corridor bends the wrong way, whereas these ones
# path perfectly. Trading that accuracy back as a speed handicap is what
# reproduces the original's actual feel -- caught only when cornered.
#
# Frightened ghosts halve this again and eaten eyes double it
# (``mode_speed_multiplier``), matching the arcade's per-mode structure.
GHOST_SPEED = 1 / 16

# The catch, in two beats like the arcade. First a still hold on the
# instant of capture -- Pac-Man normal, the ghost still on him -- so it
# registers; then the dying animation spins him away. The whole thing
# freezes the game; the respawn (and READY!) follow when it ends.
CAUGHT_PAUSE_TICKS = int(ENGINE_TICKS_PER_SECOND * 0.8)
DEATH_ANIMATION_TICKS = int(ENGINE_TICKS_PER_SECOND * 1.7)
DEATH_PAUSE_TICKS = CAUGHT_PAUSE_TICKS + DEATH_ANIMATION_TICKS

# The arcade stops dead for a beat when a ghost is caught, showing
# what it scored, before play carries on from where it left off.
EAT_PAUSE_TICKS = int(ENGINE_TICKS_PER_SECOND * 0.7)

# Interstitial banners, arcade style: a beat to read the board before
# anything moves. Shown at the start of a life/level and between levels.
READY_TEXT = "READY!"
READY_MS = 1900.0
LEVEL_CLEARED_TEXT = "LEVEL CLEARED!"
LEVEL_CLEARED_MS = 1500.0
GAME_START_TEXT = "GET READY!"
GAME_START_MS = 1500.0

MAIN_MENU_ITEMS = ("Start Game", "View Highscores", "Instructions", "Exit")
PAUSE_MENU_ITEMS = ("Resume", "Return to Main Menu")

# The How-to-Play page is drawn as a diagram, not a wall of text: the
# renderer owns the keyboard art, and pulls its wording from the two
# tables below so the copy stays here in the platform-neutral shell.
#
# Each rule is (icon, text); the icon key tells the renderer which sprite
# to stamp beside the line (a pac-gum, a super pac-gum, or a ghost).
INSTRUCTION_RULES = (
    ("pellet", "Eat every pac-gum to clear the level."),
    ("super", "Super pac-gums turn the ghosts blue and edible."),
    ("ghost", "A ghost's touch costs a life -- you respawn at center."),
    ("pacman", "Clear every level to win the game."),
)

# Cheat keys and their short captions (reviewer aids, subject VI.5),
# drawn under each F-key cap.
INSTRUCTION_CHEATS = (
    ("F1", "INVINCIBLE"),
    ("F2", "FREEZE"),
    ("F3", "+1 LIFE"),
    ("F4", "SPEED"),
    ("F5", "SKIP LEVEL"),
)


class Screen(Enum):
    """The application-level screen currently shown (subject VI.8)."""

    MAIN_MENU = auto()
    INSTRUCTIONS = auto()
    HIGHSCORES = auto()
    PLAYING = auto()
    PAUSED = auto()
    NAME_ENTRY = auto()


class Action(Enum):
    """A graphics-library-independent input intent.

    The front-end translates raw keys into these; the shell routes them
    by screen. Directional actions double as menu navigation and player
    steering. ``TYPE`` and ``BACKSPACE`` serve name entry (the typed
    character travels alongside, not in the enum).
    """

    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    CONFIRM = auto()
    BACK = auto()
    PAUSE = auto()
    CHEAT_INVINCIBLE = auto()
    CHEAT_FREEZE = auto()
    CHEAT_LIFE = auto()
    CHEAT_SPEED = auto()
    CHEAT_SKIP = auto()
    BACKSPACE = auto()
    QUIT = auto()


_ACTION_DIRECTION = {
    Action.UP: Direction.NORTH,
    Action.DOWN: Direction.SOUTH,
    Action.LEFT: Direction.WEST,
    Action.RIGHT: Direction.EAST,
}


class GameShell:
    """The screen FSM wrapping a :class:`GameSession`, sans graphics.

    Drive it with :meth:`dispatch` (one input intent) and
    :meth:`advance` (real elapsed milliseconds); read its public
    attributes to render. Highscores load once at construction (subject
    V.5) and save when a finished game's name entry is confirmed.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.highscore_path = config.highscore_filename
        self.highscores = HighscoreTable.load(self.highscore_path)
        self.session: GameSession | None = None
        self.screen = Screen.MAIN_MENU
        self.running = True
        self.menu_index = 0
        self.pause_index = 0
        self.name_buffer = ""
        self.final_score = 0
        self.final_won = False
        self._accumulator_ms = 0.0
        # Interstitials: the arcade never drops you straight into play.
        # While a banner is up the simulation does not tick at all, so
        # the board sits still under the message. Queued because some
        # moments show two in a row (level cleared, then READY!).
        self.banner_text: str | None = None
        self._banner_ms = 0.0
        self._banner_queue: list[tuple[str, float]] = []
        self._was_dying = False
        self._last_level = 0

    # -- Interstitial banners -------------------------------------------

    def _queue_banner(self, *banners: tuple[str, float]) -> None:
        """Line up one or more (text, milliseconds) interstitials."""
        self._banner_queue.extend(banners)
        if self.banner_text is None:
            self._next_banner()

    def _next_banner(self) -> None:
        """Show the next queued banner, or clear and let play resume."""
        if self._banner_queue:
            self.banner_text, self._banner_ms = self._banner_queue.pop(0)
        else:
            self.banner_text, self._banner_ms = None, 0.0

    # -- Transitions ---------------------------------------------------

    def start_new_game(self) -> None:
        """Begin a fresh session and enter the PLAYING screen.

        A session born already finished (an adversarial ``lives: 0``
        config) rolls straight into the end-of-game flow.
        """
        self.session = GameSession(
            self.config, ghost_speed=GHOST_SPEED, player_speed=PLAYER_SPEED,
            death_pause_ticks=DEATH_PAUSE_TICKS,
            eat_pause_ticks=EAT_PAUSE_TICKS,
            caught_pause_ticks=CAUGHT_PAUSE_TICKS,
        )
        self._accumulator_ms = 0.0
        self.banner_text, self._banner_ms = None, 0.0
        self._banner_queue.clear()
        self._was_dying = False
        self._last_level = self.session.level_number
        self.screen = Screen.PLAYING
        if self.session.status is not SessionStatus.RUNNING:
            self._end_game()
        else:
            self._queue_banner((GAME_START_TEXT, GAME_START_MS),
                               (READY_TEXT, READY_MS))

    def _end_game(self) -> None:
        """Capture the final result and open the name-entry screen."""
        assert self.session is not None
        self.final_score = self.session.score
        self.final_won = self.session.status is SessionStatus.VICTORY
        self.name_buffer = ""
        self.screen = Screen.NAME_ENTRY

    def _confirm_name(self) -> None:
        """Record the finished game's score, then return to the menu.

        The table sanitizes the name and ignores a non-qualifying
        score; the save is best-effort (subject V.5: never crash on I/O).
        """
        self.highscores.add(self.name_buffer, self.final_score)
        self.highscores.save(self.highscore_path)
        self.session = None
        self.screen = Screen.MAIN_MENU
        self.menu_index = 0

    # -- Input ---------------------------------------------------------

    def dispatch(self, action: Action | None, char: str = "") -> None:
        """Route one input intent to the active screen's handler.

        ``action`` is the navigational meaning (may be ``None`` for a
        plain printable key); ``char`` is the typed character used only
        by name entry. QUIT ends the loop from anywhere.
        """
        if action is Action.QUIT:
            self.running = False
            return
        handlers = {
            Screen.MAIN_MENU: self._on_main_menu,
            Screen.INSTRUCTIONS: self._on_info,
            Screen.HIGHSCORES: self._on_info,
            Screen.PLAYING: self._on_playing,
            Screen.PAUSED: self._on_pause,
            Screen.NAME_ENTRY: self._on_name_entry,
        }
        handlers[self.screen](action, char)

    def _on_main_menu(self, action: Action | None, char: str) -> None:
        if action is Action.UP:
            self.menu_index = (self.menu_index - 1) % len(MAIN_MENU_ITEMS)
        elif action is Action.DOWN:
            self.menu_index = (self.menu_index + 1) % len(MAIN_MENU_ITEMS)
        elif action is Action.BACK:
            self.running = False
        elif action is Action.CONFIRM:
            self._select_main_menu()

    def _select_main_menu(self) -> None:
        """Act on the highlighted main-menu item."""
        choice = MAIN_MENU_ITEMS[self.menu_index]
        if choice == "Start Game":
            self.start_new_game()
        elif choice == "View Highscores":
            self.screen = Screen.HIGHSCORES
        elif choice == "Instructions":
            self.screen = Screen.INSTRUCTIONS
        elif choice == "Exit":
            self.running = False

    def _on_info(self, action: Action | None, char: str) -> None:
        """Instructions / highscores: Confirm or Back returns to menu."""
        if action in (Action.CONFIRM, Action.BACK):
            self.screen = Screen.MAIN_MENU

    def _on_playing(self, action: Action | None, char: str) -> None:
        assert self.session is not None
        state = self.session.state
        if action in _ACTION_DIRECTION:
            state.buffer_input(_ACTION_DIRECTION[action])
        elif action in (Action.PAUSE, Action.BACK):
            self.pause_index = 0
            self.screen = Screen.PAUSED
        elif action is Action.CHEAT_INVINCIBLE:
            state.cheats.invincible = not state.cheats.invincible
        elif action is Action.CHEAT_FREEZE:
            state.cheats.ghosts_frozen = not state.cheats.ghosts_frozen
        elif action is Action.CHEAT_LIFE:
            state.add_life()
        elif action is Action.CHEAT_SPEED:
            state.cheats.speed_boost = not state.cheats.speed_boost
        elif action is Action.CHEAT_SKIP:
            self.session.advance_level()
            if self.session.status is not SessionStatus.RUNNING:
                self._end_game()

    def _on_pause(self, action: Action | None, char: str) -> None:
        if action is Action.UP:
            self.pause_index = (self.pause_index - 1) % len(PAUSE_MENU_ITEMS)
        elif action is Action.DOWN:
            self.pause_index = (self.pause_index + 1) % len(PAUSE_MENU_ITEMS)
        elif action in (Action.PAUSE, Action.BACK):
            self.screen = Screen.PLAYING
        elif action is Action.CONFIRM:
            if PAUSE_MENU_ITEMS[self.pause_index] == "Resume":
                self.screen = Screen.PLAYING
            else:  # Return to Main Menu: abandon the current game.
                self.session = None
                self.screen = Screen.MAIN_MENU
                self.menu_index = 0

    def _on_name_entry(self, action: Action | None, char: str) -> None:
        if action is Action.CONFIRM:
            self._confirm_name()
        elif action is Action.BACKSPACE:
            self.name_buffer = self.name_buffer[:-1]
        elif char and len(self.name_buffer) < MAX_NAME_LENGTH:
            if char.isalnum() or char == " ":
                self.name_buffer += char

    # -- Simulation ----------------------------------------------------

    def advance(self, elapsed_ms: float) -> None:
        """Advance the simulation by fixed ticks over ``elapsed_ms``.

        Only the PLAYING screen ticks -- menus and pause freeze it
        (subject VI.7). One ``session.tick()`` per :data:`MS_PER_TICK`
        of accumulated real time (REFERENCE.md §2.1); the tick that
        finishes a game hands off to the name-entry flow at once.

        An interstitial banner freezes the simulation entirely for its
        duration, so READY! and LEVEL CLEARED! are read against a still
        board rather than flashing over play already in progress.
        """
        if self.screen is not Screen.PLAYING or self.session is None:
            return
        if self.banner_text is not None:
            # Carry leftover time from one banner into the next, so a
            # long frame (or a queued pair) does not strand a message on
            # screen. Never ticks in the same call: the accumulator is
            # reset so play resumes cleanly instead of fast-forwarding
            # through the time spent reading.
            remaining = elapsed_ms
            while self.banner_text is not None and remaining > 0:
                if self._banner_ms > remaining:
                    self._banner_ms -= remaining
                    break
                remaining -= self._banner_ms
                self._next_banner()
            self._accumulator_ms = 0.0
            return
        self._accumulator_ms += elapsed_ms
        while self._accumulator_ms >= MS_PER_TICK:
            self._accumulator_ms -= MS_PER_TICK
            self.session.tick()
            if self.session.status is not SessionStatus.RUNNING:
                self._end_game()
                return
            if self._note_interstitial_moments():
                return

    def _note_interstitial_moments(self) -> bool:
        """Queue a banner if this tick just crossed a notable moment.

        Two moments the arcade always punctuates: finishing a level, and
        coming back after being caught (once the dying animation has
        run its course). Returns True when a banner was raised, so the
        caller stops ticking immediately.
        """
        assert self.session is not None
        dying = self.session.state.dying_ticks > 0
        respawned = self._was_dying and not dying
        self._was_dying = dying

        if self.session.level_number != self._last_level:
            self._last_level = self.session.level_number
            self._queue_banner((LEVEL_CLEARED_TEXT, LEVEL_CLEARED_MS),
                               (READY_TEXT, READY_MS))
            return True
        if respawned:
            self._queue_banner((READY_TEXT, READY_MS))
            return True
        return False

    # -- Render-facing views -------------------------------------------

    def highscore_lines(self) -> tuple[str, ...]:
        """Formatted leaderboard rows (or a friendly empty message)."""
        entries = self.highscores.entries
        if not entries:
            return ("No highscores yet -- be the first!",)
        return tuple(
            f"{rank:>2}. {entry.name:<10} {entry.score:>7}"
            for rank, entry in enumerate(entries, start=1)
        )
