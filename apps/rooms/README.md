# Room Planner

A small local web app for laying out furniture in a room (top-down view, metric units).

## Run

Part of dumb-home-project: start the top-level `server.py` (see the main README) and open
`https://<pi-ip>:8765/rooms/`.

## Saving

Every change is saved automatically to `rooms.json` in the server's data directory
(`~/.local/share/dumb-home-project/` by default), shortly after you make it.
The save icon in the top left shows the status, and clicking it (or pressing `Ctrl+S`) saves right away.
To back up or move your layouts, copy `rooms.json`.

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
- **Backrest / armrests**: in the selected piece's editor, enter a depth (cm) for any side to draw it as a solid,
  hatched band — e.g. a sofa's backrest. The sides are entered as seen on the plan, and the band turns with the piece.
- **Color**: pick one of the palette colors; it applies to everything selected.
- **Select several**: Shift+click pieces (or list entries).
- **Group** (`Ctrl+G`): grouped pieces move, rotate, duplicate and get removed together, which is handy for
  L-shaped furniture such as a sofa with a chaise. Clicking a grouped piece selects the whole group;
  double-click a piece to select just that part and adjust it. `Ctrl+Shift+G` ungroups.
- `Del` removes the selection, `Ctrl+D` duplicates it, `Esc` deselects.
- With snapping on, positions snap to 5 cm and angles to 15°, and pieces stick flush to walls and to neighbouring
  furniture (hold Shift while dragging to bypass).
- Pieces are outlined in red when they overlap each other (parts of the same group don't count), stick out of the room, block an inward door's swing, or are taller than the ceiling.
