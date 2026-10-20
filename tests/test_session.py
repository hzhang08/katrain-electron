import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "build/upstream"))
sys.path.insert(0, str(APP / "backend"))
from session import RestoredGame, load_session, save_session, synchronize_analysis

from katrain.core.base_katrain import KaTrainBase
from katrain.core.game import KaTrainSGF


class NoAnalysisEngine:
    def request_analysis(self, *args, **kwargs):
        raise AssertionError("Restoring a session must not request analysis")


@pytest.fixture
def owner():
    synchronize_analysis()
    gui = KaTrainBase(force_package_config=True)
    root = KaTrainSGF.parse_sgf("(;SZ[19]KM[6.5];B[dd](;W[pp])(;W[qq];B[dc]))")
    gui.game = RestoredGame(gui, NoAnalysisEngine(), root, "/missing/source.sgf")
    gui.game.set_current_node(root.children[0].children[1])
    gui.game.current_node.note = "Unsaved note\nwith [brackets] and Unicode 棋"
    gui.game.current_node.time_used = 12.5
    gui.game.main_time_used = 42
    gui.game.region_of_interest = [1, 8, 2, 9]
    gui.players_info["B"].periods_used = 2
    gui.contributing = False
    for index, node in enumerate(root.nodes_in_tree):
        node.analysis = {
            "root": {"scoreLead": 3.5, "winrate": 0.7, "visits": 100 + index},
            "moves": {
                "D16": {"move": "D16", "order": 0, "scoreLead": 3.5, "winrate": 0.7, "visits": 100, "pv": ["D16", "Q4"]}
            },
            "ownership": [0.25] * 361,
            "policy": [0.001] * 362,
            "completed": index % 2 == 0,
        }
        node.analysis_visits_requested = 500
    return gui


def test_roundtrip_without_source_or_analysis(owner, tmp_path):
    path = tmp_path / "session.json"
    view = {"rotation": 90, "show_move_num": True}
    save_session(path, owner, view)
    game, players, restored_view = load_session(path, owner, NoAnalysisEngine())
    assert game.current_node is game.root.children[0].children[1]
    assert game.current_node.note == owner.game.current_node.note
    assert game.main_time_used == 42
    assert game.region_of_interest == [1, 8, 2, 9]
    assert game.sgf_filename == "/missing/source.sgf"
    assert restored_view == view
    assert players["B"].periods_used == 2
    for restored, original in zip(game.root.nodes_in_tree, owner.game.root.nodes_in_tree):
        assert restored.analysis == original.analysis
        assert restored.analysis_visits_requested == original.analysis_visits_requested
        assert restored.properties == original.properties
    assert game.stones == owner.game.stones


def test_atomic_failure_preserves_last_save(owner, tmp_path, monkeypatch):
    import session

    path = tmp_path / "session.json"
    save_session(path, owner, {})
    previous = path.read_bytes()
    owner.game.current_node.note = "new"

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(session.os, "replace", fail)
    with pytest.raises(OSError):
        save_session(path, owner, {})
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("damage", ["version", "parent", "position", "cache"])
def test_rejects_invalid_snapshot(owner, tmp_path, damage):
    path = tmp_path / "session.json"
    save_session(path, owner, {})
    data = json.loads(path.read_text())
    if damage == "version":
        data["version"] = 999
    elif damage == "parent":
        data["game"]["nodes"][1]["parent"] = 999
    elif damage == "position":
        data["game"]["current_node"] = -1
    else:
        data["game"]["nodes"][0]["analysis"] = {}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_session(path, owner, NoAnalysisEngine())
