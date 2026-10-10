# Room Planner

A small local web app for laying out furniture in a room (top-down view, metric units).

## Run

```
python3 server.py
```

This opens http://127.0.0.1:8000 in your browser (use `--port` to pick another port, `--no-browser` to skip opening it).
It only needs Python 3, with no extra packages.

## Saving

Every change is saved automatically to `data.json` in this folder, shortly after you make it.
The save icon in the top left shows the status, and clicking it (or pressing `Ctrl+S`) saves right away.
To back up or move your layouts, copy `data.json`.

If you open `index.html` directly without the server, the app still works, but the icon shows **Browser only**.
Changes are then kept only in that browser, not in the folder.

## Snapshots

A snapshot saves the current furniture arrangement of a room (positions, rotations, colors, groups) under a name,
so you can try out alternatives and switch between them.

- **Save snapshot**: stores the arrangement that is on the plan right now.
- Click a snapshot (or use **Previous / Next**) to restore it. If the current arrangement isn't saved in any
  snapshot, you're asked before it gets replaced.
- *on plan* marks the snapshot that matches the plan; *modified* means you've changed things since restoring it.
  ⤓ overwrites a snapshot with the current arrangement, ✎ renames it, ✕ deletes it.
- Snapshots don't include the room size, doors or windows, so restoring never undoes changes to the room itself.

## Usage

- **New room**: set the width, length and ceiling height (cm), then add doors and windows per wall.
  The offset is measured from the left corner (top/bottom walls) or the top corner (left/right walls).
- **Add furniture** (in the Furniture panel): give it a name, width, length and height.
- **Move**: drag a piece, or use the arrow keys (1 cm, Shift = 10 cm).
- **Rotate**: drag the ● handle, use the rotate buttons, or press `R` (90°) / `Shift+R` (15°).
- **Color**: pick one of the palette colors; it applies to everything selected.
- **Select several**: Shift+click pieces (or list entries).
- **Group** (`Ctrl+G`): grouped pieces move, rotate, duplicate and get removed together, which is handy for
  L-shaped furniture such as a sofa with a chaise. Clicking a grouped piece selects the whole group;
  double-click a piece to select just that part and adjust it. `Ctrl+Shift+G` ungroups.
- `Del` removes the selection, `Ctrl+D` duplicates it, `Esc` deselects.
- With snapping on, positions snap to 5 cm and angles to 15°, and pieces stick flush to walls and to neighbouring
  furniture (hold Shift while dragging to bypass).
- Pieces are outlined in red when they overlap each other (parts of the same group don't count), stick out of the room, block an inward door's swing, or are taller than the ceiling.
