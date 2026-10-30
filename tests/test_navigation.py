import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "build/upstream"))
sys.path.insert(0, str(APP / "backend"))
from katrain.core.game import KaTrainSGF
from navigation import node_at_move


def test_jump_and_branch_preservation():
    root = KaTrainSGF.parse_sgf("(;SZ[19];B[dd](;W[pp])(;W[qq];B[dc]))")
    selected = root.children[0].children[1]
    assert node_at_move(selected, 0) is root
    assert node_at_move(selected, 2) is selected
    assert node_at_move(selected, 3) is selected.children[0]
    assert node_at_move(selected, 1) is selected.parent
    assert node_at_move(root, 2) is root.children[0].ordered_children[0]
    with pytest.raises(ValueError, match="ends at move 3"):
        node_at_move(selected, 86)


def test_move_86_and_passes():
    root = KaTrainSGF.parse_sgf("(;SZ[19]" + ";B[];W[]" * 50 + ")")
    assert node_at_move(root, 86).depth == 86


@pytest.mark.parametrize("number", [-1, 1.5, "86", None, True])
def test_invalid_numbers(number):
    with pytest.raises(ValueError):
        node_at_move(None, number)
