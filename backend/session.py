"""Versioned, self-contained game snapshots for KaTrain Electron."""

import copy
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from katrain.core.base_katrain import Player
from katrain.core.game import BaseGame, Game
from katrain.core.game_node import GameNode

ANALYSIS_LOCK = threading.RLock()
NODE_FIELDS = ("note", "time_used", "end_state", "ai_thoughts", "auto_undo", "undo_threshold", "played_mistake_sound")


def synchronize_analysis():
    """Snapshot reads and asynchronous result updates share one lock."""
    import functools

    for name in ("set_analysis", "clear_analysis", "update_move_analysis"):
        original = getattr(GameNode, name)
        if getattr(original, "_session_locked", False):
            continue

        def wrap(method):
            @functools.wraps(method)
            def locked(*args, **kwargs):
                with ANALYSIS_LOCK:
                    return method(*args, **kwargs)

            locked._session_locked = True
            return locked

        setattr(GameNode, name, wrap(original))


class RestoredGame(Game):
    def __init__(self, owner, engine, root, filename):
        # Match the pinned Game constructor without its analysis-launching thread.
        BaseGame.__init__(self, owner, move_tree=root, sgf_filename=filename)
        self.engines = {"B": engine, "W": engine}
        self.insert_mode = False
        self.insert_after = None
        self.region_of_interest = None


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = file.name
            json.dump(payload, file, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save_session(path, gui, view):
    game = gui.game
    if not game or gui.contributing:
        return False
    with game._lock, ANALYSIS_LOCK:
        nodes, stack = [], [game.root]
        while stack:
            node = stack.pop()
            nodes.append(node)
            stack.extend(reversed(node.children))
        indices = {node: index for index, node in enumerate(nodes)}
        payload = {
            "format": "katrain-electron-session",
            "version": 1,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "engine": {
                key: copy.deepcopy(gui.config("engine").get(key))
                for key in ("backend", "model", "humanlike_model", "max_visits", "fast_visits", "max_time")
            },
            "game": {
                "filename": game.sgf_filename,
                "current_node": indices[game.current_node],
                "main_time_used": game.main_time_used,
                "external_game": game.external_game,
                "region_of_interest": game.region_of_interest,
                "insert_mode": game.insert_mode,
                "insert_after": indices.get(game.insert_after),
                "players": {bw: vars(player).copy() for bw, player in gui.players_info.items()},
                "nodes": [
                    {
                        "parent": indices.get(node.parent),
                        "properties": copy.deepcopy(node.properties),
                        **{field: copy.deepcopy(getattr(node, field)) for field in NODE_FIELDS},
                        "analysis": copy.deepcopy(node.analysis),
                        "analysis_visits_requested": node.analysis_visits_requested,
                        "shortcuts": [indices[target] for target, _via in node.shortcuts_to if target in indices],
                    }
                    for node in nodes
                ],
            },
            "view": copy.deepcopy(view),
        }
    atomic_json(path, payload)
    return True


def load_session(path, owner, engine):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != "katrain-electron-session" or data.get("version") != 1:
        raise ValueError("Unsupported session format/version")
    record = data["game"]
    if not isinstance(record["nodes"], list) or not record["nodes"]:
        raise ValueError("Session has no game tree")
    nodes = []
    for index, saved in enumerate(record["nodes"]):
        parent = saved["parent"]
        if (index == 0 and parent is not None) or (index > 0 and (type(parent) is not int or not 0 <= parent < index)):
            raise ValueError("Invalid parent reference")
        properties = saved["properties"]
        if not isinstance(properties, dict) or any(not isinstance(v, list) for v in properties.values()):
            raise ValueError("Invalid SGF properties")
        analysis = saved["analysis"]
        if (
            not isinstance(analysis, dict)
            or not {"root", "moves", "policy", "ownership", "completed"} <= analysis.keys()
        ):
            raise ValueError("Invalid analysis cache")
        if not isinstance(analysis["moves"], dict) or (
            analysis["root"] is not None and not isinstance(analysis["root"], dict)
        ):
            raise ValueError("Invalid analysis values")
        node = GameNode(parent=nodes[parent] if index else None, properties=properties)
        for field in NODE_FIELDS:
            setattr(node, field, saved[field])
        node.analysis = analysis
        node.analysis_visits_requested = saved["analysis_visits_requested"]
        nodes.append(node)

    def reference(index):
        if type(index) is not int or not 0 <= index < len(nodes):
            raise ValueError("Invalid node reference")
        return nodes[index]

    game = RestoredGame(owner, engine, nodes[0], record["filename"])
    game.set_current_node(reference(record["current_node"]))
    game.main_time_used = record["main_time_used"]
    game.external_game = record["external_game"]
    game.region_of_interest = record["region_of_interest"]
    game.insert_after = reference(record["insert_after"]) if record["insert_after"] is not None else None
    game.insert_mode = bool(record["insert_mode"] and game.insert_after is not None)
    for node, saved in zip(nodes, record["nodes"]):
        for target in saved["shortcuts"]:
            node.add_shortcut(reference(target))
    players = {bw: Player(bw) for bw in "BW"}
    for bw, player in players.items():
        for name in vars(player):
            if name in record["players"][bw]:
                setattr(player, name, record["players"][bw][name])
    view = data["view"]
    if view.get("rotation", 0) not in (0, 90, 180, 270):
        raise ValueError("Invalid board rotation")
    return game, players, view
