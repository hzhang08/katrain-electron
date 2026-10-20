# isort: skip_file
"""Run unmodified, single-board KaTrain behind the Electron window.

A private stdin/stdout bridge carries input and lossless rendered frames. No
HTTP server, screen recording, separate visible Kivy window, or external Python
installation is required by the packaged application.
"""

import base64
import json
import os
import queue
import signal
import struct
import sys
import threading
import time
import shutil
import zlib
from pathlib import Path

# Keep application logs separate from the framed protocol, including imports.
protocol = sys.stdout
sys.stdout = sys.stderr
os.environ.update(KIVY_NO_ARGS="1", KIVY_NO_CONSOLELOG="1", KIVY_NO_FILELOG="1", KIVY_LOG_MODE="PYTHON")
user_dir = Path(os.environ["KATRAIN_ELECTRON_DATA"])
user_dir.mkdir(parents=True, exist_ok=True)
os.environ["KIVY_HOME"] = str(user_dir / "kivy")
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build/upstream"))

from kivy.config import Config

Config.set("graphics", "window_state", "hidden")
Config.set("graphics", "width", "1300")
Config.set("graphics", "height", "1000")
Config.set("graphics", "maxfps", "30")
Config.set("kivy", "exit_on_escape", "0")

# Isolate configuration, KataGo cache, themes, and output from both native apps.
import katrain.core.constants as constants

constants.DATA_FOLDER = str(user_dir)
# KaTrain must preload sound before Kivy creates the SDL window on macOS.
from katrain.__main__ import KaTrainApp, KaTrainGui
from katrain.core.utils import PATHS
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Keyboard, Window
from kivy.graphics import ClearBuffers, ClearColor, Fbo, Scale, Translate
from kivy.input.motionevent import MotionEvent
from katrain.gui.widgets.panels import AnalysisToggle, CollapsablePanel
from session import save_session, load_session, synchronize_analysis

synchronize_analysis()


write_lock = threading.Lock()
commands = queue.Queue()


def send(kind, **data):
    with write_lock:
        protocol.write(json.dumps({"type": kind, **data}, separators=(",", ":")) + "\n")
        protocol.flush()


def read_commands():
    try:
        for line in sys.stdin:
            try:
                commands.put(json.loads(line))
            except (ValueError, TypeError):
                pass
    finally:
        commands.put({"type": "quit"})


def png_rgba(width, height, pixels):
    def chunk(name, data):
        return struct.pack("!I", len(data)) + name + data + struct.pack("!I", zlib.crc32(name + data))

    stride = width * 4
    rows = b"".join(b"\0" + pixels[y : y + stride] for y in range(0, len(pixels), stride))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 1))
        + chunk(b"IEND", b"")
    )


class Pointer(MotionEvent):
    def __init__(self, uid, x, y, button):
        super().__init__("electron", uid, {"x": x, "y": y}, is_touch=True, type_id="touch")
        self.profile = ["pos", "button"]
        self.button = button

    def depack(self, args):
        self.sx, self.sy = args["x"], args["y"]
        super().depack(args)


class ElectronKaTrain(KaTrainApp):
    def build(self):
        KaTrainGui.USER_CONFIG_FILE = str(user_dir / "config.json")
        config_file = Path(KaTrainGui.USER_CONFIG_FILE)
        config = json.loads(
            config_file.read_text() if config_file.exists() else (Path(PATHS["PACKAGE"]) / "config.json").read_text()
        )
        resources = Path(os.environ["KATRAIN_ELECTRON_RESOURCES"])
        # Resolve bundled defaults on every launch so the .app remains movable.
        for field, default in {
            "katago": str(resources / "engine/katago"),
            "model": str(resources / "engine/model.bin.gz"),
            "config": str(Path(PATHS["PACKAGE"]) / "KataGo/analysis_config.cfg"),
        }.items():
            old = config["engine"].get(field, "")
            if (
                not old
                or not Path(old).is_file()
                or "KaTrain Electron.app/Contents/Resources" in old
                or old.startswith("katrain/")
            ):
                config["engine"][field] = default
        config["general"]["debug_level"] = 0
        config["general"]["sgf_save"] = str(user_dir / "sgf")
        config["ui_state"]["restoresize"] = False
        config_file.write_text(json.dumps(config, indent=2))
        self.touches = {}
        self.last_pixels = None
        self.in_flight = False
        self.fbo = None
        self.frame_size = None
        self.stopping = False
        self.saving_disabled = False
        self.restored_session = False
        self.startup_warning = None
        root = super().build()
        Window.hide()
        return root

    def on_start(self):
        new_game = self.gui._do_new_game

        def restore_or_new(*args, **kwargs):
            if not self.restore_session():
                new_game(*args, **kwargs)

        self.gui._do_new_game = restore_or_new
        try:
            super().on_start()
        finally:
            self.gui._do_new_game = new_game
        self.gui._do_electron_close = lambda: Clock.schedule_once(self.finish_close, 0)
        if self.startup_warning:
            Clock.schedule_once(lambda _dt: send("session-warning", message=self.startup_warning), 1)
        Window.hide()
        threading.Thread(target=read_commands, daemon=True).start()
        Clock.schedule_interval(self.pump, 1 / 60)
        Clock.schedule_interval(self.render_frame, 1 / 20)
        Clock.schedule_interval(self.checkpoint, 15)
        self.last_recent_game = (None, None)
        Clock.schedule_interval(self.report_open_game, 0.5)
        send("ready", version=constants.VERSION)

    def report_open_game(self, *_):
        # Observe the resulting game, not an open request: failed loads must
        # not enter history. This also covers Kivy's file chooser and Save As.
        game = getattr(self.gui, "game", None)
        filename = getattr(game, "sgf_filename", None)
        current = (game, filename)
        if current != self.last_recent_game:
            self.last_recent_game = current
            if filename:
                send("game-opened", path=os.path.abspath(filename))

    def session_view(self):
        gui = self.gui
        return {
            "mode": gui.play_analyze_mode,
            "rotation": gui.board_gui.rotation_degree,
            "show_move_num": gui.show_move_num,
            "coordinates": gui.board_gui.draw_coords_enabled,
            "zen": gui.zen,
            "analysis_controls": {
                name: toggle.active
                for name, toggle in gui.analysis_controls.ids.items()
                if isinstance(toggle, AnalysisToggle)
            },
            "panels": {
                name: [panel.state, panel.option_state]
                for name, panel in gui.controls.ids.items()
                if isinstance(panel, CollapsablePanel)
            },
        }

    def checkpoint(self, *_):
        if self.saving_disabled:
            return
        try:
            save_session(user_dir / "session.json", self.gui, self.session_view())
        except Exception as error:
            send("session-warning", message=f"Could not save session: {error}")

    def restore_session(self):
        path = user_dir / "session.json"
        if not path.exists():
            return False
        try:
            game, players, view = load_session(path, self.gui, self.gui.engine)
        except Exception as error:
            try:
                backup = path.with_name(f"session.unreadable-{time.time_ns()}.json")
                shutil.copy2(path, backup)
                self.startup_warning = (
                    f"Could not restore the previous session: {error}. A copy was preserved at {backup}."
                )
            except OSError:
                self.saving_disabled = True
                self.startup_warning = (
                    f"Could not restore or back up {path}. Automatic saving is disabled to preserve it."
                )
            return False
        gui = self.gui
        gui.game, gui.players_info = game, players
        # Open paused in Analysis, so an AI or teaching undo cannot move away
        # from the saved position. Cached/partial results are never re-requested.
        gui.pondering = False
        gui.play_mode.play.state = "normal"
        gui.play_mode.analyze.state = "down"
        gui.play_mode.select_mode(constants.MODE_ANALYZE)
        gui.controls.timer.paused = True
        gui.controls.last_timer_update = (game.current_node, time.time(), False)
        gui.controls.update_players()
        gui.controls.graph.initialize_from_game(game.root)
        gui.controls.move_tree.insert_node = game.insert_after if game.insert_mode else None
        gui.show_move_num = bool(view.get("show_move_num", False))
        gui.board_gui.draw_coords_enabled = bool(view.get("coordinates", True))
        gui.zen = view.get("zen", 0)
        for name, active in view.get("analysis_controls", {}).items():
            toggle = gui.analysis_controls.ids.get(name)
            if isinstance(toggle, AnalysisToggle):
                toggle.checkbox.active = bool(active)
        for name, (state, options) in view.get("panels", {}).items():
            panel = gui.controls.ids.get(name)
            if isinstance(panel, CollapsablePanel):
                panel.state = state
                panel.set_option_state(options)
        gui.play_mode.save_ui_state()
        gui.board_gui.draw_board()
        while gui.board_gui.rotation_degree != view.get("rotation", 0):
            gui.board_gui.rotate_gridpos()
        gui.update_state(redraw_board=True)
        self.restored_session = True
        return True

    def finish_close(self, *_):
        try:
            if self.saving_disabled:
                raise RuntimeError("Session saving is disabled because the previous snapshot could not be backed up.")
            save_session(user_dir / "session.json", self.gui, self.session_view())
        except Exception as error:
            self.stopping = False
            send("save-error", message=f"Session could not be saved: {error}")
            return
        send("session-saved")
        self.on_request_close()
        self.stop()

    def pump(self, _dt):
        for _ in range(200):
            try:
                event = commands.get_nowait()
            except queue.Empty:
                break
            try:
                self.handle(event)
            except Exception as error:
                import traceback

                traceback.print_exc()
                send("error", message=str(error))

    def handle(self, event):
        kind = event.get("type")
        if self.stopping and kind not in ("ack", "inspect", "quit"):
            return
        if kind == "ack":
            self.in_flight = False
        elif kind == "resize":
            Window.size = (max(800, min(2400, int(event["width"]))), max(600, min(1800, int(event["height"]))))
            self.last_pixels = None
        elif kind in ("down", "move", "up", "wheel"):
            x, y = max(0, min(1, event["x"])), max(0, min(1, 1 - event["y"]))
            Window.mouse_pos = (x * Window.width, y * Window.height)
            Window._modifiers = event.get("modifiers", [])
            uid = event.get("id", 1)
            if kind in ("down", "wheel"):
                touch = Pointer(uid, x, y, event.get("button", "left"))
                touch.is_double_tap = bool(event.get("double", False))
                EventLoop.post_dispatch_input("begin", touch)
                if kind == "wheel":
                    EventLoop.post_dispatch_input("end", touch)
                else:
                    self.touches[uid] = touch
            elif uid in self.touches:
                touch = self.touches[uid]
                touch.move({"x": x, "y": y})
                EventLoop.post_dispatch_input("update" if kind == "move" else "end", touch)
                if kind == "up":
                    self.touches.pop(uid, None)
        elif kind in ("keydown", "keyup"):
            name = event["key"]
            code = Keyboard.keycodes.get(name, ord(name) if len(name) == 1 else -1)
            modifiers = event.get("modifiers", [])
            Window._modifiers = modifiers
            if kind == "keydown":
                if not Window.dispatch("on_key_down", code, code, event.get("text", ""), modifiers):
                    Window.dispatch("on_keyboard", code, code, event.get("text", ""), modifiers)
            else:
                Window.dispatch("on_key_up", code, code)
        elif kind == "text":
            Window.dispatch("on_textinput", event["text"])
        elif kind == "blur":
            for touch in self.touches.values():
                EventLoop.post_dispatch_input("end", touch)
            self.touches.clear()
            Window._modifiers = []
        elif kind == "clipboard":
            Clipboard.copy(event["text"])
        elif kind == "open":
            self.gui.load_sgf_file(event["path"], fast=True, rewind=True)
        elif kind == "action":
            allowed = {
                "new-game-popup",
                "analyze-sgf-popup",
                "save-game",
                "save-game-as-popup",
                "undo",
                "redo",
                "ai-move",
            }
            if event["action"] in allowed:
                self.gui(event["action"], *event.get("args", []))
        elif kind == "inspect" and os.environ.get("KATRAIN_ELECTRON_TEST") == "1":
            game = self.gui.game
            board = self.gui.board_gui
            send(
                "inspection",
                request=event.get("request"),
                depth=game.current_node.depth if game else None,
                stones=[(s.gtp(), s.player) for s in game.stones] if game else [],
                analysis=game.current_node.analysis if game else {},
                note=self.gui.controls.note.text,
                popup=bool(self.gui.popup_open),
                board=[list(p) for row in (board.gridpos or []) for p in row],
                size=list(Window.size),
                logicalSize=list(Window.system_size),
                children=len(Window.children),
                noteBounds=[*self.gui.controls.note.pos, *self.gui.controls.note.size],
                notesTab=list(self.gui.controls.notes_panel.option_buttons[2].center),
                selectedMode=self.gui.play_analyze_mode,
                restored=self.restored_session,
                queryCounter=self.gui.engine.query_counter,
                nodeCount=len(game.root.nodes_in_tree),
            )
        elif kind == "quit":
            if not self.stopping:
                self.stopping = True
                self.gui.pondering = False
                self.gui.controls.timer.paused = True
                self.gui.play_mode.select_mode(constants.MODE_ANALYZE)
                # A queue barrier saves after already accepted moves/AI actions.
                if self.gui.game and not self.gui.contributing:
                    self.gui("electron-close")
                else:
                    Clock.schedule_once(self.finish_close, 0)

    def render_frame(self, _dt):
        if self.in_flight or self.stopping:
            return
        width, height = map(int, Window.size)
        if self.frame_size != (width, height):
            self.fbo = Fbo(size=(width, height), with_stencilbuffer=True)
            with self.fbo:
                ClearColor(0.13, 0.18, 0.23, 1)
                ClearBuffers()
                Scale(1, -1, 1)
                Translate(0, -height, 0)
            self.frame_size = (width, height)
        # Window.canvas includes popups, dropdowns and tooltips as well as root.
        self.fbo.add(Window.canvas)
        try:
            self.fbo.draw()
            pixels = self.fbo.pixels
        finally:
            self.fbo.remove(Window.canvas)
        if pixels == self.last_pixels:
            return
        self.last_pixels = pixels
        self.in_flight = True
        send("frame", width=width, height=height, png=base64.b64encode(png_rgba(width, height, pixels)).decode("ascii"))


if __name__ == "__main__":
    app = ElectronKaTrain()
    signal.signal(signal.SIGTERM, lambda *_: commands.put({"type": "quit"}))
    app.run()
