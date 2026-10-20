# KaTrain Electron session save format

KaTrain Electron saves its current game and analysis automatically every **15 seconds** and when it closes normally. It restores them on the next launch, without needing the original SGF file or rerunning KataGo analysis.

## File location

On this Mac:

```text
~/Library/Application Support/KaTrain Electron/session.json
```

Use **File → Show App Data** to find it. The snapshot belongs only to KaTrain Electron; KaTrain Workspace and the original KaTrain app use their own data. The file is ordinary UTF-8 JSON, with no pickle or executable objects. It is not encrypted.

## Design

The snapshot is a self-contained game tree plus a complete per-node analysis cache. I chose JSON rather than SGF alone because a session needs to preserve partial analysis, the exact selected variation, timers, editable notes, and view settings as well as the moves. Source SGF files are never overwritten by autosaving.

The top-level structure is:

| Field | Meaning |
| --- | --- |
| `format` | Always `katrain-electron-session`. |
| `version` | Integer schema version; currently `1`. Unknown versions are rejected. |
| `saved_at` | UTC ISO-8601 timestamp of the snapshot. |
| `engine` | Analysis provenance: backend, model paths, visits and time limits. This does not replace engine settings on restore. |
| `game` | Full game tree, selected node, game state, and player settings. |
| `view` | Board rotation, coordinates, move numbers, analysis overlays and panel options. |

Actual files use compact JSON. This small example is formatted for readability and represents an empty game without cached analysis:

```json
{
  "format": "katrain-electron-session",
  "version": 1,
  "saved_at": "2026-10-17T19:00:00+00:00",
  "engine": {
    "backend": "",
    "model": "/path/to/model.bin.gz",
    "humanlike_model": "",
    "max_visits": 500,
    "fast_visits": 25,
    "max_time": 8.0
  },
  "game": {
    "filename": null,
    "current_node": 0,
    "main_time_used": 0,
    "external_game": false,
    "region_of_interest": null,
    "insert_mode": false,
    "insert_after": null,
    "players": { "B": {}, "W": {} },
    "nodes": [
      {
        "parent": null,
        "properties": { "SZ": ["19"], "KM": ["6.5"], "RU": ["Japanese"] },
        "note": "",
        "time_used": 0,
        "end_state": null,
        "ai_thoughts": "",
        "auto_undo": null,
        "undo_threshold": 0.5,
        "played_mistake_sound": null,
        "analysis": {
          "root": null,
          "moves": {},
          "ownership": null,
          "policy": null,
          "completed": false
        },
        "analysis_visits_requested": 0,
        "shortcuts": []
      }
    ]
  },
  "view": {
    "mode": "analyze",
    "rotation": 0,
    "show_move_num": false,
    "coordinates": true,
    "zen": 0,
    "analysis_controls": {},
    "panels": {}
  }
}
```

### Tree representation

`game.nodes` is a depth-first preorder traversal using each node's stored child order. Every node has a zero-based array index. The root is index `0` with `parent: null`; every other node points to an earlier parent index. Siblings retain their relative order in the array. Thus all side variations are retained, not just the current line.

`current_node` points to the exact position selected before closing. `properties` stores the original SGF property dictionary as lists of values, including moves, setup stones, player names, board size, komi, and rules. Editable comments live in the separate `note` field. `shortcuts` contains indices of branch-collapse targets. `insert_after` is a node index or `null`.

Each player entry contains the original Player object's fields: color, player type, subtype/AI strategy, name, SGF rank, calculated rank, and periods used. Empty dictionaries in the example use default human players.

### Analysis cache

The `analysis` object is copied directly from KaTrain's in-memory analysis for that position:

- `root`: position evaluation, including visits, score lead, win rate and any other fields returned by KataGo.
- `moves`: dictionary keyed by GTP coordinate, such as `D16` or `pass`. Entries preserve visit counts, evaluation, ordering, principal variation (`pv`), and other returned fields.
- `ownership`: original flat ownership array, or `null` when unavailable.
- `policy`: original flat move-policy array, or `null` when unavailable; normally includes the pass entry.
- `completed`: whether the original analysis finished. An incomplete search remains marked incomplete.

Array order and numeric values are retained as provided by KaTrain; the session layer does not rotate, round, or reinterpret them. `analysis_visits_requested` preserves the previous requested budget for subsequent deeper-analysis commands.

This saves **analysis results**, not KataGo's internal neural-network or search-tree memory. Complete and partial results are displayed immediately on restore. No cached node is automatically reanalyzed, and interrupted searches are not automatically resumed. Use the existing analysis controls to request additional analysis when desired. New moves are analyzed normally.

Cached results remain the results from the original model/settings, even if engine settings later change. The stored engine metadata describes their provenance; it does not silently invalidate or recompute the cache.

### Game and view state

The snapshot also preserves notes, AI explanations, teaching state, per-node elapsed time, the game clock total, player setup, region of interest, insert-mode position, rotation, coordinates, move numbers, analysis toggles, and panel visibility/options.

Sessions reopen **paused in Analysis mode**, with pondering off. This deliberately prevents AI play, teaching retries, or running clocks from changing the restored position before the user acts. The saved `view.mode` records the mode at the time of the checkpoint; reopening does not resume automatic play. Window size and placement remain in Electron's existing `window.json` file.

## Saving and shutdown

Analysis callbacks and snapshot reads share a lock so a result cannot be copied halfway through an update. The game tree is captured while holding its game lock. JSON is written to a unique temporary file in the same directory, flushed and `fsync`ed, then atomically replaces `session.json`. A failed write leaves the previous successful snapshot intact and cleans up the temporary file.

Normal close/Quit queues a save after already accepted game actions. Electron waits for a successful save acknowledgment before allowing its backend shutdown timeout. A save error keeps the application open and reports the error so the user can resolve it and retry closing.

Force Quit, power loss, or an OS crash can bypass the close handler. In those cases, the last completed periodic snapshot is available; changes since that checkpoint may be lost.

## Validation and recovery

Loading checks the format/version, tree references, property and analysis structure, selected-node reference, and rotation. An unreadable or unsupported snapshot is copied to `session.unreadable-<timestamp>.json` before starting a new game. If the backup cannot be made, autosaving is disabled to avoid destroying the original file, and the app reports the problem.

The older `recovery.sgf` file is separate. Earlier Electron builds did not store a complete analysis cache, so this feature cannot retroactively recover analysis that those builds already discarded. Their recovery SGF remains available from the existing recovery menu.

## Implementation and verification

- `backend/session.py`: serialization, atomic writes, validation, and construction without analysis requests.
- `backend/host.py`: automatic checkpoints, startup restoration, UI state, and shutdown save barrier.
- `app/main.cjs`: waits for save acknowledgment and reports save failures.
- `tests/test_session.py`: branches, exact complete/partial caches, notes, missing source SGFs, failed writes, and invalid snapshots.
- `scripts/test-session.cjs`: runs the Electron interaction test, then starts a fresh process and verifies the saved cache and zero analysis requests on reopening.
