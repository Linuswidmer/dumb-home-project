'use strict';

/*
 * Room Planner — all dimensions are stored in centimetres.
 * Room coordinates: origin at the inner top-left corner, x to the right, y down.
 * Furniture x/y is its center; width runs along x and length along y at rotation 0.
 * Pieces can share a groupId (see room.groups) to move and rotate together, e.g. a corner sofa.
 */

const STORAGE_KEY = 'room-planner-v1';
const API = 'api/state';  // relative to /rooms/; served by routes.py, stored in rooms.json
const SAVE_DELAY = 600;    // ms of inactivity before autosaving
const WALL = 12;        // drawn wall thickness (cm)
const GRID_SNAP = 5;    // position snap step (cm)
const ANGLE_SNAP = 15;  // rotation snap step (degrees)
const MAGNET_PX = 10;   // screen distance at which furniture sticks to a wall
const EPS = 0.5;        // tolerance for overlap checks (cm)
const COLORS = [
  ['Blue', '#3b6fd1'],
  ['Orange', '#d0743c'],
  ['Green', '#3f9a5b'],
  ['Purple', '#9a5cc6'],
  ['Mustard', '#c49a1f'],
  ['Teal', '#2b9c9c'],
  ['Red', '#c4475f'],
  ['Grey', '#6b7280'],
  ['Navy', '#2c3e7a'],
  ['Olive', '#7f8a2b'],
  ['Brown', '#8a5a3b'],
  ['Pink', '#d46ca6'],
];
const OPENING_DEFAULTS = {
  door: { width: 90, height: 205, hinge: 'start', swing: 'inward' },
  window: { width: 120, height: 130, sill: 90 },
};

const $ = (sel) => document.querySelector(sel);
const svg = $('#plan');

let state = normalizeState(null);
let selection = []; // ids of selected furniture
let drag = null;     // active pointer drag: move or rotate of the selection
let pxToCm = 1;    // cm per screen pixel, updated on every plan render
let draft = null;  // room being edited in the dialog: { id, openings }

/* ---------- persistence ---------- */

function normalizeState(s) {
  const out = {
    rooms: Array.isArray(s && s.rooms) ? s.rooms : [],
    currentRoomId: s && s.currentRoomId,
    snap: s && typeof s.snap === 'boolean' ? s.snap : true,
    showGrid: s && typeof s.showGrid === 'boolean' ? s.showGrid : true,
  };
  for (const r of out.rooms) {
    r.openings = Array.isArray(r.openings) ? r.openings : [];
    r.furniture = Array.isArray(r.furniture) ? r.furniture : [];
    r.groups = Array.isArray(r.groups) ? r.groups : [];
    r.snapshots = Array.isArray(r.snapshots) ? r.snapshots : [];
    for (const f of r.furniture) if (!r.groups.some((g) => g.id === f.groupId)) f.groupId = null;
  }
  if (!out.rooms.some((r) => r.id === out.currentRoomId)) out.currentRoomId = out.rooms[0] ? out.rooms[0].id : null;
  return out;
}

/*
 * data.json in the app folder (via server.py) is the source of truth. The browser's
 * localStorage is only a fallback when the page is opened without the server.
 */
const SAVE_LABELS = {
  saved: 'Saved',
  pending: 'Unsaved changes',
  saving: 'Saving…',
  error: 'Save failed – retry',
  offline: 'Browser only',
};
const SAVE_TITLES = {
  saved: 'All changes are saved to data.json (Ctrl+S)',
  pending: 'Changes will be saved to data.json in a moment – click to save now (Ctrl+S)',
  saving: 'Writing data.json…',
  error: 'Could not write data.json – is server.py still running? Click to retry.',
  offline: 'Not connected to server.py, so changes are only kept in this browser. Start the app with "python3 server.py" to save to the folder.',
};

let serverAvailable = false;
let saveStatus = 'saved';
let saveTimer = null;
let saveInFlight = false;
let saveAgain = false;

function loadLocal() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)); } catch { return null; }
}

async function loadState() {
  const local = loadLocal();
  try {
    const res = await fetch(API, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const remote = await res.json();
    serverAvailable = true;
    if (remote && Array.isArray(remote.rooms)) return normalizeState(remote);
    // No data.json yet: start from whatever this browser had and write it out.
    const s = normalizeState(local);
    if (s.rooms.length) scheduleSave(0);
    return s;
  } catch {
    setSaveStatus('offline');
    return normalizeState(local);
  }
}

function saveState() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { /* storage unavailable */ }
  if (serverAvailable) scheduleSave(SAVE_DELAY);
}

function scheduleSave(delay) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, delay);
  setSaveStatus('pending');
}

async function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  if (saveInFlight) { saveAgain = true; return; } // keep writes in order
  saveInFlight = true;
  setSaveStatus('saving');
  try {
    const res = await fetch(API, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    serverAvailable = true;
    setSaveStatus(saveAgain || saveTimer ? 'pending' : 'saved');
  } catch {
    setSaveStatus(serverAvailable ? 'error' : 'offline');
  } finally {
    saveInFlight = false;
    if (saveAgain) { saveAgain = false; saveNow(); }
  }
}

function setSaveStatus(status) {
  saveStatus = status;
  const btn = $('#saveBtn');
  btn.dataset.status = status;
  btn.title = SAVE_TITLES[status];
  $('#saveLabel').textContent = SAVE_LABELS[status];
}

$('#saveBtn').addEventListener('click', saveNow);

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    saveNow();
  }
});

window.addEventListener('beforeunload', (e) => {
  if (saveStatus === 'pending' && serverAvailable) {
    // Flush the debounced save; keepalive lets the request outlive the page.
    clearTimeout(saveTimer);
    fetch(API, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state), keepalive: true });
  } else if (saveStatus === 'error' || saveStatus === 'saving') {
    e.preventDefault();
  }
});

/* ---------- helpers ---------- */

const uid = () => Math.random().toString(36).slice(2, 10);
const num = (v, fallback = 0) => { const n = parseFloat(v); return Number.isFinite(n) ? n : fallback; };
const snapTo = (v, step) => Math.round(v / step) * step;
const round1 = (v) => Math.round(v * 10) / 10;
const round2 = (v) => Math.round(v * 100) / 100;
const normDeg = (a) => round1(((a % 360) + 360) % 360);
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const fmtM = (cm) => (cm / 100).toFixed(2) + ' m';
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const mul = (a, k) => [a[0] * k, a[1] * k];
const pt = (p) => `${p[0]} ${p[1]}`;
const angleDeg = (p, center) => (Math.atan2(p[1] - center[1], p[0] - center[0]) * 180) / Math.PI;

const currentRoom = () => state.rooms.find((r) => r.id === state.currentRoomId) || null;
const groupById = (r, id) => r.groups.find((g) => g.id === id) || null;
const groupMembers = (r, id) => r.furniture.filter((f) => f.groupId === id);
// A piece plus all other members of its group.
const withGroup = (f) => (f.groupId ? groupMembers(currentRoom(), f.groupId) : [f]);
const label = (r, f) => f.name || (f.groupId && groupById(r, f.groupId) ? groupById(r, f.groupId).name : 'Unnamed');

/*
 * Solid edges (backrest, armrests) are stored per piece in f.backrest, keyed by edge (top/right/bottom/left)
 * in the piece's own frame (top = -y at rotation 0), so they turn with the piece. A value is either a depth
 * in cm (band runs the full edge) or { depth, length, from } for a band covering only part of the edge,
 * starting at the edge's 'start' (-x / -y end) or 'end'.
 */
const EDGES = ['top', 'right', 'bottom', 'left'];
const edgeLength = (f, edge) => (edge === 'top' || edge === 'bottom' ? f.width : f.length);

function edgeSpec(f, edge) {
  const v = (f.backrest || {})[edge];
  const raw = v && typeof v === 'object' ? v : { depth: v };
  const across = edge === 'top' || edge === 'bottom' ? f.length : f.width;
  const full = edgeLength(f, edge);
  const length = num(raw.length) > 0 ? Math.min(num(raw.length), full) : full;
  return { depth: Math.min(Math.max(0, num(raw.depth)), across), length, full, from: raw.from === 'end' ? 'end' : 'start' };
}

function setEdgeSpec(f, edge, { depth, length, from }) {
  const full = edgeLength(f, edge);
  const partial = length > 0 && length < full;
  f.backrest = { ...f.backrest, [edge]: partial ? { depth, length, from } : depth };
  if (!depth) delete f.backrest[edge];
  if (!Object.keys(f.backrest).length) delete f.backrest;
}

function edgeDepths(f) {
  const d = {};
  for (const e of EDGES) d[e] = edgeSpec(f, e).depth;
  return d;
}

const quarterTurns = (f) => ((Math.round(f.rotation / 90) % 4) + 4) % 4;

// Which local edge of a piece currently faces the given side of the plan (nearest 90° step).
function localEdge(f, planSide) {
  return EDGES[(EDGES.indexOf(planSide) - quarterTurns(f) + 4) % 4];
}

// Whether a local edge's 'start' end currently lies at the top/left end of its side on the plan.
function startIsPlanStart(f, edge) {
  let v = edge === 'top' || edge === 'bottom' ? [-1, 0] : [0, -1];
  for (let i = 0; i < quarterTurns(f); i++) v = [-v[1], v[0]]; // 90° clockwise on screen
  return v[0] + v[1] < 0;
}

// Rectangles (piece frame) covered by the solid edges.
function edgeRects(f) {
  const hw = f.width / 2, hl = f.length / 2;
  const rects = [];
  for (const edge of EDGES) {
    const { depth, length, from } = edgeSpec(f, edge);
    if (!depth) continue;
    if (edge === 'top' || edge === 'bottom') {
      const x = from === 'start' ? -hw : hw - length;
      rects.push([x, edge === 'top' ? -hl : hl - depth, length, depth]);
    } else {
      const y = from === 'start' ? -hl : hl - length;
      rects.push([edge === 'left' ? -hw : hw - depth, y, depth, length]);
    }
  }
  return rects;
}

// Solid edges drawn through one clip path, so corners where bands meet aren't painted twice.
function drawBands(f, clipId, fillAttrs) {
  const rects = edgeRects(f);
  if (!rects.length) return '';
  const hw = f.width / 2, hl = f.length / 2;
  return `<clipPath id="${clipId}">${rects.map(([x, y, w, h]) => `<rect x="${x}" y="${y}" width="${w}" height="${h}"/>`).join('')}</clipPath>` +
    fillAttrs.map((attrs) => `<rect x="${-hw}" y="${-hl}" width="${f.width}" height="${f.length}" clip-path="url(#${clipId})" ${attrs}/>`).join('');
}

function selectedItems() {
  const r = currentRoom();
  return r ? r.furniture.filter((f) => selection.includes(f.id)) : [];
}

// The group whose members are exactly the current selection, if any.
function selectionGroup() {
  const r = currentRoom(), items = selectedItems();
  if (!r || items.length < 2 || !items[0].groupId) return null;
  const id = items[0].groupId;
  if (!items.every((f) => f.groupId === id) || groupMembers(r, id).length !== items.length) return null;
  return groupById(r, id);
}

// Groups need at least two members; anything else is dissolved.
function cleanGroups(r) {
  r.groups = r.groups.filter((g) => groupMembers(r, g.id).length >= 2);
  for (const f of r.furniture) if (f.groupId && !groupById(r, f.groupId)) f.groupId = null;
}

/* ---------- geometry ---------- */

// Position and orientation of a wall: start corner, direction along the wall, normal pointing into the room.
function wallFrame(r, wall) {
  switch (wall) {
    case 'top': return { start: [0, 0], dir: [1, 0], inward: [0, 1], len: r.width };
    case 'bottom': return { start: [0, r.length], dir: [1, 0], inward: [0, -1], len: r.width };
    case 'left': return { start: [0, 0], dir: [0, 1], inward: [1, 0], len: r.length };
    default: return { start: [r.width, 0], dir: [0, 1], inward: [-1, 0], len: r.length };
  }
}

function openingGeom(r, o) {
  const f = wallFrame(r, o.wall);
  return { f, a: add(f.start, mul(f.dir, o.offset)), b: add(f.start, mul(f.dir, o.offset + o.width)) };
}

function corners(f) {
  const a = (f.rotation * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  const hw = f.width / 2, hl = f.length / 2;
  return [[-hw, -hl], [hw, -hl], [hw, hl], [-hw, hl]].map(([x, y]) => [f.x + x * c - y * s, f.y + x * s + y * c]);
}

// Axis-aligned bounding box around one or more (rotated) pieces.
function bbox(items) {
  const pts = items.flatMap(corners);
  const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
  const b = { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  b.center = [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
  return b;
}

// Separating axis test for two convex polygons; touching edges do not count as overlap.
function polysOverlap(A, B) {
  for (const P of [A, B]) {
    for (let i = 0; i < P.length; i++) {
      const p1 = P[i], p2 = P[(i + 1) % P.length];
      const len = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) || 1;
      const n = [(p2[1] - p1[1]) / len, (p1[0] - p2[0]) / len];
      const proj = (Q) => Q.map((q) => q[0] * n[0] + q[1] * n[1]);
      const pa = proj(A), pb = proj(B);
      if (Math.max(...pa) <= Math.min(...pb) + EPS || Math.max(...pb) <= Math.min(...pa) + EPS) return false;
    }
  }
  return true;
}

// Map of furniture id -> list of human-readable problems.
function findIssues(r) {
  const issues = new Map();
  const flag = (id, msg) => {
    if (!issues.has(id)) issues.set(id, []);
    if (!issues.get(id).includes(msg)) issues.get(id).push(msg);
  };
  const polys = r.furniture.map(corners);
  const swings = r.openings
    .filter((o) => o.type === 'door' && o.swing !== 'outward')
    .map((o) => {
      const { f, a, b } = openingGeom(r, o);
      const d = mul(f.inward, o.width);
      return [a, b, add(b, d), add(a, d)];
    });

  r.furniture.forEach((f, i) => {
    if (polys[i].some(([x, y]) => x < -EPS || y < -EPS || x > r.width + EPS || y > r.length + EPS)) flag(f.id, 'outside the room');
    if (f.height > r.height) flag(f.id, 'taller than the ceiling');
    if (swings.some((sw) => polysOverlap(polys[i], sw))) flag(f.id, 'in a door swing');
    for (let j = i + 1; j < r.furniture.length; j++) {
      const other = r.furniture[j];
      if (f.groupId && f.groupId === other.groupId) continue; // parts of one piece may touch or overlap
      if (polysOverlap(polys[i], polys[j])) {
        flag(f.id, `overlaps ${label(r, other)}`);
        flag(other.id, `overlaps ${label(r, f)}`);
      }
    }
  });
  return issues;
}

/* ---------- rendering ---------- */

function render() {
  document.body.classList.toggle('no-room', !currentRoom());
  renderRoomSelect();
  renderPlan();
  renderList();
  renderSelected();
  renderStats();
  renderSnapshots();
  renderPanelSummaries();
  $('#snapToggle').checked = state.snap;
  $('#gridToggle').checked = state.showGrid;
}

function renderRoomSelect() {
  $('#roomSelect').innerHTML = state.rooms
    .map((r) => `<option value="${r.id}"${r.id === state.currentRoomId ? ' selected' : ''}>${esc(r.name)}</option>`)
    .join('');
}

function renderStats() {
  const r = currentRoom();
  if (!r) { $('#roomStats').textContent = ''; return; }
  const area = (r.width * r.length) / 10000;
  const used = r.furniture.reduce((s, f) => s + f.width * f.length, 0) / 10000;
  $('#roomStats').innerHTML =
    `${fmtM(r.width)} × ${fmtM(r.length)} · ceiling ${fmtM(r.height)}<br>` +
    `Floor ${area.toFixed(2)} m² · furniture ${used.toFixed(2)} m² (${Math.round((used / area) * 100)}%) · ` +
    `free ${Math.max(area - used, 0).toFixed(2)} m²`;
}

function renderPlan() {
  const r = currentRoom();
  $('#emptyState').hidden = !!r;
  $('#hint').hidden = !r;
  if (!r) { svg.innerHTML = ''; svg.removeAttribute('viewBox'); return; }

  const outward = r.openings
    .filter((o) => o.type === 'door' && o.swing === 'outward')
    .reduce((m, o) => Math.max(m, o.width), 0);
  const pad = Math.max(70, WALL + outward + 30);
  const vb = [-pad, -pad, r.width + 2 * pad, r.length + 2 * pad];
  svg.setAttribute('viewBox', vb.join(' '));
  const box = svg.getBoundingClientRect();
  pxToCm = box.width && box.height ? Math.max(vb[2] / box.width, vb[3] / box.height) : 1;
  const k = pxToCm;

  let s = `<defs>
    <pattern id="gridMinor" width="10" height="10" patternUnits="userSpaceOnUse">
      <path d="M10 0H0V10" fill="none" stroke="#eef0f4" stroke-width="${k}"/>
    </pattern>
    <pattern id="gridMajor" width="100" height="100" patternUnits="userSpaceOnUse">
      <rect width="100" height="100" fill="url(#gridMinor)"/>
      <path d="M100 0H0V100" fill="none" stroke="#d5dae2" stroke-width="${k}"/>
    </pattern>
    <pattern id="hatch" width="${7 * k}" height="${7 * k}" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="${7 * k}" stroke="#000" stroke-opacity=".22" stroke-width="${2 * k}"/>
    </pattern>
  </defs>`;

  s += `<rect class="wall" x="${-WALL}" y="${-WALL}" width="${r.width + 2 * WALL}" height="${r.length + 2 * WALL}"/>`;
  s += `<rect class="floor" x="0" y="0" width="${r.width}" height="${r.length}"/>`;
  if (state.showGrid) s += `<rect x="0" y="0" width="${r.width}" height="${r.length}" fill="url(#gridMajor)"/>`;
  for (const o of r.openings) s += drawOpening(r, o);

  const fs = 13 * k;
  s += `<text class="dim" x="${r.width / 2}" y="${-WALL - 8 * k}" text-anchor="middle" font-size="${fs}">${fmtM(r.width)}</text>`;
  s += `<text class="dim" transform="translate(${-WALL - 8 * k} ${r.length / 2}) rotate(-90)" text-anchor="middle" font-size="${fs}">${fmtM(r.length)}</text>`;

  const issues = findIssues(r);
  const isSel = (f) => selection.includes(f.id);
  // Selected pieces are drawn last so they stay on top while dragging.
  const ordered = [...r.furniture].sort((a, b) => isSel(a) - isSel(b));
  const single = selection.length === 1;
  for (const f of ordered) s += drawFurniture(f, issues.has(f.id), isSel(f), single && isSel(f));
  if (selection.length > 1) s += drawSelectionBox(selectedItems());

  svg.innerHTML = s;
}

function drawOpening(r, o) {
  const { f, a, b } = openingGeom(r, o);
  const out = mul(f.inward, -WALL);
  const gap = [a, b, add(b, out), add(a, out)].map(pt).join(' ');
  const title = o.type === 'door'
    ? `Door ${o.width} × ${o.height} cm, opens ${o.swing}`
    : `Window ${o.width} × ${o.height} cm, sill at ${o.sill} cm`;
  let s = `<g class="opening"><title>${title}</title>`;

  if (o.type === 'window') {
    const m1 = mul(f.inward, -WALL * 0.35), m2 = mul(f.inward, -WALL * 0.65);
    s += `<polygon class="window-frame" points="${gap}"/>`;
    s += `<line class="glass" x1="${a[0] + m1[0]}" y1="${a[1] + m1[1]}" x2="${b[0] + m1[0]}" y2="${b[1] + m1[1]}"/>`;
    s += `<line class="glass" x1="${a[0] + m2[0]}" y1="${a[1] + m2[1]}" x2="${b[0] + m2[0]}" y2="${b[1] + m2[1]}"/>`;
  } else {
    const outward = o.swing === 'outward';
    const dir = outward ? mul(f.inward, -1) : f.inward;
    const base = outward ? out : [0, 0]; // hinge sits on the face of the wall the door opens towards
    const hinge = add(o.hinge === 'end' ? b : a, base);
    const other = add(o.hinge === 'end' ? a : b, base);
    const leaf = add(hinge, mul(dir, o.width));
    const v1 = sub(leaf, hinge), v2 = sub(other, hinge);
    const sweep = v1[0] * v2[1] - v1[1] * v2[0] > 0 ? 1 : 0;
    s += `<polygon class="wall-gap" points="${gap}"/>`;
    s += `<path class="door-swing" d="M${pt(hinge)} L${pt(leaf)} A${o.width} ${o.width} 0 0 ${sweep} ${pt(other)} Z"/>`;
    s += `<line class="door-leaf" x1="${hinge[0]}" y1="${hinge[1]}" x2="${leaf[0]}" y2="${leaf[1]}"/>`;
  }
  return s + '</g>';
}

// Angle in [-90, 90) so text is never upside down.
function uprightAngle(a) {
  a = ((a % 360) + 360) % 360;
  if (a >= 90 && a < 270) return a - 180;
  return a >= 270 ? a - 360 : a;
}

function rotationHandle(x, top) {
  const k = pxToCm, hy = top - 24 * k;
  return `<line class="rot-stem" x1="${x}" y1="${top}" x2="${x}" y2="${hy}"/>` +
    `<circle class="rot-handle" data-rotate="1" cx="${x}" cy="${hy}" r="${7 * k}"><title>Drag to rotate</title></circle>`;
}

function drawFurniture(f, conflict, sel, handle) {
  const k = pxToCm;
  const d = edgeDepths(f);
  // Labels go in the open (seat) area that's left after the solid edges.
  const w = Math.max(f.width - d.left - d.right, 1), l = Math.max(f.length - d.top - d.bottom, 1);
  const cx = (d.left - d.right) / 2, cy = (d.top - d.bottom) / 2;
  const wide = w >= l;
  const along = wide ? w : l, across = wide ? l : w;
  // Label runs along the longer side of the piece and is kept upright.
  const textRot = uprightAngle(f.rotation + (wide ? 0 : 90)) - f.rotation;
  const name = f.name || '';
  const fsName = Math.max(9 * k, Math.min(across * 0.3, (along * 0.9) / Math.max(name.length * 0.62, 1), 22 * k));
  const fsDim = Math.max(8 * k, Math.min(fsName * 0.75, 13 * k));
  const showDims = along >= fsDim * 9 && (name ? across >= (fsName + fsDim) * 1.35 : across >= fsDim * 1.5);
  const cls = `furn${sel ? ' selected' : ''}${conflict ? ' conflict' : ''}${f.groupId ? ' grouped' : ''}`;

  let s = `<g class="${cls}" data-id="${f.id}" transform="translate(${f.x} ${f.y}) rotate(${f.rotation})">`;
  s += `<rect class="body" x="${-f.width / 2}" y="${-f.length / 2}" width="${f.width}" height="${f.length}" style="fill:${f.color};stroke:${f.color}"/>`;
  s += drawBands(f, `bands-${f.id}`, [`class="band" style="fill:${f.color}"`, 'class="band-hatch"']);
  s += `<g transform="translate(${cx} ${cy}) rotate(${textRot})">`;
  if (name) {
    s += `<text class="label-name" text-anchor="middle" dominant-baseline="central" y="${showDims ? -fsDim * 0.55 : 0}" font-size="${fsName}">${esc(name)}</text>`;
  }
  if (showDims) {
    s += `<text class="label-dims" text-anchor="middle" dominant-baseline="central" y="${name ? fsName * 0.65 : 0}" font-size="${fsDim}">${f.width}×${f.length}×${f.height}</text>`;
  }
  s += '</g>';
  if (handle) s += rotationHandle(0, -f.length / 2);
  return s + '</g>';
}

function drawSelectionBox(items) {
  const k = pxToCm, b = bbox(items), m = 6 * k;
  return `<rect class="sel-box" x="${b.minX - m}" y="${b.minY - m}" width="${b.maxX - b.minX + 2 * m}" height="${b.maxY - b.minY + 2 * m}"/>` +
    rotationHandle(b.center[0], b.minY - m);
}

function renderList() {
  const r = currentRoom();
  const ul = $('#furnitureList');
  if (!r) { ul.innerHTML = ''; return; }
  if (!r.furniture.length) { ul.innerHTML = '<li class="muted">Nothing yet — add a piece above.</li>'; return; }
  const issues = findIssues(r);
  const item = (f, member) => `
    <li data-id="${f.id}" class="${member ? 'member' : ''}${selection.includes(f.id) ? ' active' : ''}">
      <span class="swatch" style="background:${f.color}"></span>
      <span>${f.name ? esc(f.name) : '<em class="muted">no label</em>'}</span>
      <span class="dims">${f.width}×${f.length}×${f.height} cm</span>
      ${issues.has(f.id) ? `<span class="warn">⚠ ${esc(issues.get(f.id).join(', '))}</span>` : ''}
    </li>`;

  const listed = new Set();
  let html = '';
  for (const f of r.furniture) {
    if (listed.has(f.id)) continue;
    const g = f.groupId && groupById(r, f.groupId);
    if (!g) { html += item(f, false); continue; }
    const members = groupMembers(r, g.id);
    members.forEach((m) => listed.add(m.id));
    const b = bbox(members);
    html += `
      <li data-group="${g.id}" class="group${selectionGroup() === g ? ' active' : ''}">
        <span class="group-icon">⧉</span>
        <span>${esc(g.name)}</span>
        <span class="dims">${Math.round(b.maxX - b.minX)}×${Math.round(b.maxY - b.minY)} cm · ${members.length} parts</span>
      </li>`;
    html += members.map((m) => item(m, true)).join('');
  }
  ul.innerHTML = html;
}

/* ---------- collapsible sidebar panels ---------- */

const PANELS_KEY = 'room-planner-panels';
let lastSelectionKey = '';

function panel(name) {
  return $(`.panel[data-panel="${name}"]`);
}

// Open/closed state of the panels is a per-browser preference, so it lives in localStorage.
function restorePanels() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(PANELS_KEY)) || {}; } catch { /* use defaults */ }
  for (const el of document.querySelectorAll('.panel')) {
    if (el.dataset.panel in saved) el.open = saved[el.dataset.panel];
    el.addEventListener('toggle', () => {
      const state = {};
      for (const p of document.querySelectorAll('.panel')) state[p.dataset.panel] = p.open;
      try { localStorage.setItem(PANELS_KEY, JSON.stringify(state)); } catch { /* not persisted */ }
    });
  }
}

function renderPanelSummaries() {
  const r = currentRoom();
  if (!r) {
    $('#roomSummary').textContent = 'No room yet';
    panel('room').open = true; // the only thing to do is create one
    return;
  }
  $('#roomSummary').innerHTML = `${esc(r.name)} <span class="muted">${fmtM(r.width)} × ${fmtM(r.length)}</span>`;
  const active = findSnapshot(r, r.activeSnapshotId);
  const n = r.snapshots.length;
  $('#snapshotSummary').innerHTML = n
    ? `${n} saved${active ? ` <span class="muted">· ${esc(active.name)}${snapshotMatches(r, active) ? '' : ' (modified)'}</span>` : ''}`
    : '<span class="muted">none yet</span>';
  const pieces = r.furniture.length;
  $('#furnitureSummary').innerHTML = `${pieces} ${pieces === 1 ? 'piece' : 'pieces'}` +
    (selection.length ? ` <span class="muted">· ${selection.length} selected</span>` : '');
}

function setField(el, value) {
  if (el !== document.activeElement) el.value = value; // don't fight the user while typing
}

function renderSelected() {
  const r = currentRoom(), items = selectedItems();
  $('#selectedSection').hidden = !items.length;
  // Selecting something on the plan brings up its editor, even if the panel was collapsed.
  const key = selection.join();
  if (key !== lastSelectionKey) {
    lastSelectionKey = key;
    if (items.length) panel('furniture').open = true;
  }
  if (!items.length) return;

  const single = items.length === 1 ? items[0] : null;
  const group = selectionGroup();
  const partOf = single && single.groupId ? groupById(r, single.groupId) : null;
  const form = $('#selectedForm');

  $('#selectedTitle').textContent = group ? 'Selected group' : partOf ? 'Selected part of a group' : single ? 'Selected furniture' : `${items.length} pieces selected`;
  $('#groupFields').hidden = !(group || partOf);
  if (group || partOf) setField(form.elements.namedItem('groupName'), (group || partOf).name);
  $('#selectWholeGroupBtn').hidden = !partOf;
  $('#detachBtn').hidden = !partOf;

  $('#singleFields').hidden = !single;
  if (single) {
    for (const key of ['name', 'width', 'length', 'height', 'x', 'y', 'rotation']) {
      // not elements[key]: elements.length is the element count
      setField(form.elements.namedItem(key), typeof single[key] === 'number' ? round1(single[key]) : single[key]);
    }
    // Edge fields and the little preview show the piece as it currently sits on the plan.
    for (const side of EDGES) {
      const edge = localEdge(single, side);
      const spec = edgeSpec(single, edge);
      setField(form.elements.namedItem(`edge-${side}`), spec.depth || '');
      $(`.edge-len[data-side="${side}"]`).hidden = !spec.depth;
      setField(form.elements.namedItem(`len-${side}`), spec.length < spec.full ? spec.length : '');
      form.elements.namedItem(`len-${side}`).placeholder = `${spec.full}`;
      const planFrom = (spec.from === 'start') === startIsPlanStart(single, edge) ? 'start' : 'end';
      setField(form.elements.namedItem(`from-${side}`), planFrom);
    }
    const q = quarterTurns(single);
    const planW = q % 2 ? single.length : single.width, planH = q % 2 ? single.width : single.length;
    $('#edgePreview').setAttribute('viewBox', `${-planW / 2} ${-planH / 2} ${planW} ${planH}`);
    $('#edgePreview').innerHTML = `<g transform="rotate(${q * 90})">
      <rect x="${-single.width / 2}" y="${-single.length / 2}" width="${single.width}" height="${single.length}" fill="${single.color}" fill-opacity=".3"/>
      ${drawBands(single, 'preview-bands', ['fill="#1f2328" fill-opacity=".75"'])}</g>`;
  }

  const b = bbox(items);
  $('#selectionInfo').textContent = single ? '' : `Overall footprint ${Math.round(b.maxX - b.minX)} × ${Math.round(b.maxY - b.minY)} cm`;
  $('#selectionInfo').hidden = !!single;

  const colors = new Set(items.map((f) => f.color));
  for (const btn of $('#palette').children) btn.classList.toggle('active', colors.size === 1 && colors.has(btn.dataset.color));

  $('#groupBtn').hidden = items.length < 2 || !!group;
  $('#ungroupBtn').hidden = !group;
}

/* ---------- furniture actions ---------- */

function select(ids) {
  selection = ids;
  render();
}

function commit() {
  const r = currentRoom();
  if (r) cleanGroups(r);
  selection = selection.filter((id) => r && r.furniture.some((f) => f.id === id));
  saveState();
  render();
}

// Remember positions so moves and rotations are always computed from the starting point.
const snapshot = (items) => items.map((f) => ({ f, x: f.x, y: f.y, rotation: f.rotation }));

function rotateAround(orig, pivot, delta) {
  const a = (delta * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  for (const o of orig) {
    const vx = o.x - pivot[0], vy = o.y - pivot[1];
    o.f.x = round2(pivot[0] + vx * c - vy * s);
    o.f.y = round2(pivot[1] + vx * s + vy * c);
    o.f.rotation = normDeg(o.rotation + delta);
  }
}

function rotateSelected(delta) {
  const items = selectedItems();
  if (!items.length) return;
  if (items.length === 1) items[0].rotation = normDeg(items[0].rotation + delta);
  else rotateAround(snapshot(items), bbox(items).center, delta);
  commit();
}

function moveSelected(dx, dy) {
  for (const f of selectedItems()) { f.x = round1(f.x + dx); f.y = round1(f.y + dy); }
  commit();
}

function duplicateSelected() {
  const r = currentRoom(), items = selectedItems();
  if (!items.length) return;
  const newGroups = new Map(); // old group id -> new group id
  const copies = items.map((f) => {
    let groupId = null;
    // Copies stay grouped only when the whole group was copied.
    if (f.groupId && withGroup(f).every((m) => selection.includes(m.id))) {
      if (!newGroups.has(f.groupId)) {
        const g = { id: uid(), name: groupById(r, f.groupId).name };
        r.groups.push(g);
        newGroups.set(f.groupId, g.id);
      }
      groupId = newGroups.get(f.groupId);
    }
    return { ...clone(f), id: uid(), groupId, x: f.x + 20, y: f.y + 20 };
  });
  r.furniture.push(...copies);
  selection = copies.map((f) => f.id);
  commit();
}

function removeSelected() {
  const r = currentRoom();
  if (!r || !selection.length) return;
  r.furniture = r.furniture.filter((f) => !selection.includes(f.id));
  selection = [];
  commit();
}

function groupSelected() {
  const r = currentRoom(), items = selectedItems();
  if (items.length < 2) return;
  const previous = [...new Set(items.map((f) => f.groupId).filter(Boolean))];
  const named = items.find((f) => f.name);
  const name = previous.length === 1 ? groupById(r, previous[0]).name : named ? named.name : 'Group';
  const g = { id: uid(), name };
  r.groups.push(g);
  for (const f of items) f.groupId = g.id;
  commit();
}

function ungroupSelected() {
  const g = selectionGroup();
  if (!g) return;
  for (const f of selectedItems()) f.groupId = null;
  commit();
}

// Shift+click style toggling: add the ids, or remove them if they are all selected already.
function toggleSelection(ids) {
  const all = ids.every((id) => selection.includes(id));
  select(all ? selection.filter((id) => !ids.includes(id)) : [...new Set([...selection, ...ids])]);
  return !all;
}

$('#addFurnitureForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const r = currentRoom();
  if (!r) return;
  const fd = new FormData(e.target);
  const f = {
    id: uid(),
    name: fd.get('name').trim(),
    width: Math.max(1, num(fd.get('width'), 100)),
    length: Math.max(1, num(fd.get('length'), 60)),
    height: Math.max(1, num(fd.get('height'), 75)),
    x: r.width / 2,
    y: r.length / 2,
    rotation: 0,
    color: COLORS[r.furniture.length % COLORS.length][1],
    groupId: null,
  };
  r.furniture.push(f);
  selection = [f.id];
  e.target.elements.name.value = '';
  $('#addFurniture').open = false;
  commit();
});

$('#palette').innerHTML = COLORS
  .map(([name, color]) => `<button type="button" class="color" data-color="${color}" title="${name}" style="background:${color}"></button>`)
  .join('');
$('#palette').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-color]');
  if (!btn) return;
  for (const f of selectedItems()) f.color = btn.dataset.color;
  commit();
});

$('#selectedForm').addEventListener('input', (e) => {
  const r = currentRoom(), items = selectedItems();
  const { name, value } = e.target;
  if (name === 'groupName') {
    const g = selectionGroup() || (items.length === 1 && items[0].groupId && groupById(r, items[0].groupId));
    if (g) g.name = value;
    commit();
    return;
  }
  const f = items.length === 1 ? items[0] : null;
  if (!f) return;
  if (name === 'name') f.name = value;
  else if (/^(edge|len|from)-/.test(name)) {
    const [field, side] = name.split('-');
    const edge = localEdge(f, side);
    const spec = edgeSpec(f, edge);
    if (field === 'edge') spec.depth = Math.max(0, num(value));
    if (field === 'len') spec.length = Math.max(0, num(value));
    // The 'from' choice is made in plan terms (top/left vs bottom/right); store it in the piece's frame.
    if (field === 'from') spec.from = (value === 'start') === startIsPlanStart(f, edge) ? 'start' : 'end';
    setEdgeSpec(f, edge, spec);
  }
  else if (name === 'rotation') f.rotation = normDeg(num(value, f.rotation));
  else if (name === 'x' || name === 'y') f[name] = num(value, f[name]);
  else if (['width', 'length', 'height'].includes(name) && num(value) > 0) f[name] = num(value);
  else return;
  commit();
});

$('#selectedForm').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-rot]');
  if (btn) rotateSelected(num(btn.dataset.rot));
});
$('#duplicateBtn').addEventListener('click', duplicateSelected);
$('#removeBtn').addEventListener('click', removeSelected);
$('#groupBtn').addEventListener('click', groupSelected);
$('#ungroupBtn').addEventListener('click', ungroupSelected);
$('#selectWholeGroupBtn').addEventListener('click', () => {
  const [f] = selectedItems();
  if (f) select(withGroup(f).map((m) => m.id));
});
$('#detachBtn').addEventListener('click', () => {
  const [f] = selectedItems();
  if (!f) return;
  f.groupId = null;
  commit();
});

$('#furnitureList').addEventListener('click', (e) => {
  const li = e.target.closest('li[data-id], li[data-group]');
  if (!li) return;
  const ids = li.dataset.group ? groupMembers(currentRoom(), li.dataset.group).map((f) => f.id) : [li.dataset.id];
  if (e.shiftKey) toggleSelection(ids);
  else select(ids);
});

/* ---------- dragging on the plan ---------- */

function svgPoint(e) {
  const m = svg.getScreenCTM();
  if (!m) return [0, 0];
  const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
  return [p.x, p.y];
}

function startDrag(e, d) {
  drag = d;
  try { svg.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
  svg.classList.add('dragging');
  e.preventDefault();
}

svg.addEventListener('pointerdown', (e) => {
  const r = currentRoom();
  if (!r || e.button !== 0) return;
  const p = svgPoint(e);

  if (e.target.closest('[data-rotate]')) {
    const items = selectedItems();
    startDrag(e, items.length === 1
      ? { mode: 'rotate', single: items[0] }
      : { mode: 'rotate', pivot: bbox(items).center, a0: angleDeg(p, bbox(items).center), orig: snapshot(items) });
    return;
  }

  const g = e.target.closest('.furn');
  const f = g && r.furniture.find((x) => x.id === g.dataset.id);
  if (!f) { if (!e.shiftKey && selection.length) select([]); return; }

  const ids = withGroup(f).map((x) => x.id);
  if (e.shiftKey) {
    if (!toggleSelection(ids)) return; // just deselected, nothing to drag
  } else if (!selection.includes(f.id)) {
    select(ids); // clicking a grouped piece selects the whole group
  }
  startDrag(e, { mode: 'move', anchor: f, start: p, orig: snapshot(selectedItems()) });
});

// Double-click a grouped piece to select only that part, e.g. to adjust it within the group.
svg.addEventListener('dblclick', (e) => {
  const g = e.target.closest('.furn');
  if (g) select([g.dataset.id]);
});

// Pull the moved selection flush against walls and neighbouring furniture when an edge comes close.
function magnet(r, orig, dx, dy) {
  const ids = new Set(orig.map((o) => o.f.id));
  const b = bbox(orig.map((o) => ({ ...o.f, x: o.x + dx, y: o.y + dy })));
  const m = MAGNET_PX * pxToCm;
  const xs = [0, r.width], ys = [0, r.length];
  for (const f of r.furniture) {
    if (ids.has(f.id)) continue;
    const o = bbox([f]);
    // Only consider pieces that are next to the selection, not ones across the room.
    if (o.minY < b.maxY + m && o.maxY > b.minY - m) xs.push(o.minX, o.maxX);
    if (o.minX < b.maxX + m && o.maxX > b.minX - m) ys.push(o.minY, o.maxY);
  }
  const pull = (lo, hi, targets) => {
    let best = 0, dist = m;
    for (const t of targets) {
      for (const edge of [lo, hi]) {
        if (Math.abs(t - edge) < dist) { dist = Math.abs(t - edge); best = t - edge; }
      }
    }
    return best;
  };
  return [dx + pull(b.minX, b.maxX, xs), dy + pull(b.minY, b.maxY, ys)];
}

svg.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const r = currentRoom(), p = svgPoint(e);
  const snapping = state.snap && !e.shiftKey;

  if (drag.mode === 'rotate' && drag.single) {
    const f = drag.single;
    let angle = angleDeg(p, [f.x, f.y]) + 90;
    if (snapping) angle = snapTo(angle, ANGLE_SNAP);
    f.rotation = normDeg(angle);
  } else if (drag.mode === 'rotate') {
    let delta = angleDeg(p, drag.pivot) - drag.a0;
    if (snapping) delta = snapTo(delta, ANGLE_SNAP);
    rotateAround(drag.orig, drag.pivot, delta);
  } else {
    let dx = p[0] - drag.start[0], dy = p[1] - drag.start[1];
    if (snapping) {
      // Snap the piece under the cursor to the grid; the rest of the selection follows.
      const a = drag.orig.find((o) => o.f === drag.anchor) || drag.orig[0];
      dx = snapTo(a.x + dx, GRID_SNAP) - a.x;
      dy = snapTo(a.y + dy, GRID_SNAP) - a.y;
      [dx, dy] = magnet(r, drag.orig, dx, dy);
    }
    for (const o of drag.orig) {
      o.f.x = round1(o.x + dx);
      o.f.y = round1(o.y + dy);
    }
  }
  renderPlan();
  renderList();
  renderSelected();
});

function endDrag() {
  if (!drag) return;
  drag = null;
  svg.classList.remove('dragging');
  commit();
}
svg.addEventListener('pointerup', endDrag);
svg.addEventListener('pointercancel', endDrag);

new ResizeObserver(() => renderPlan()).observe(svg);

document.addEventListener('keydown', (e) => {
  if ($('#roomDialog').open || (e.target.closest && e.target.closest('input, select, textarea'))) return;
  if (!selection.length) return;
  const step = e.shiftKey ? 10 : 1;
  const ctrl = e.ctrlKey || e.metaKey;
  switch (e.key) {
    case 'ArrowLeft': moveSelected(-step, 0); break;
    case 'ArrowRight': moveSelected(step, 0); break;
    case 'ArrowUp': moveSelected(0, -step); break;
    case 'ArrowDown': moveSelected(0, step); break;
    case 'r': case 'R': if (ctrl) return; rotateSelected(e.shiftKey ? ANGLE_SNAP : 90); break;
    case 'Delete': case 'Backspace': removeSelected(); break;
    case 'Escape': select([]); break;
    case 'd': case 'D': if (!ctrl) return; duplicateSelected(); break;
    case 'g': case 'G': if (!ctrl) return; if (e.shiftKey) ungroupSelected(); else groupSelected(); break;
    default: return;
  }
  e.preventDefault();
});

/* ---------- snapshots ---------- */

/*
 * A snapshot is a named copy of a room's furniture arrangement (pieces + groups).
 * Room size, doors and windows are not part of it, so restoring never undoes room edits.
 */

const clone = (v) => JSON.parse(JSON.stringify(v));

// Compact fingerprint of an arrangement, used to tell whether it matches a snapshot.
function layoutKey(furniture, groups) {
  return JSON.stringify([
    furniture.map((f) => [f.id, f.name, f.width, f.length, f.height, f.x, f.y, f.rotation, f.color, f.groupId || null, EDGES.map((e) => edgeSpec(f, e))]),
    groups.map((g) => [g.id, g.name]),
  ]);
}

const snapshotMatches = (r, snap) => layoutKey(r.furniture, r.groups) === layoutKey(snap.furniture, snap.groups);
const findSnapshot = (r, id) => r.snapshots.find((s) => s.id === id) || null;
const fmtDate = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

function saveSnapshot() {
  const r = currentRoom();
  if (!r) return;
  const input = $('#snapshotName');
  const snap = {
    id: uid(),
    name: input.value.trim() || `Snapshot ${r.snapshots.length + 1}`,
    createdAt: new Date().toISOString(),
    furniture: clone(r.furniture),
    groups: clone(r.groups),
  };
  r.snapshots.push(snap);
  r.activeSnapshotId = snap.id;
  input.value = '';
  commit();
}

function restoreSnapshot(id) {
  const r = currentRoom(), snap = r && findSnapshot(r, id);
  if (!snap || snapshotMatches(r, snap)) {
    if (snap) { r.activeSnapshotId = snap.id; commit(); }
    return;
  }
  const unsaved = r.furniture.length && !r.snapshots.some((s) => snapshotMatches(r, s));
  if (unsaved && !confirm(`The current arrangement isn't saved in any snapshot and will be lost.\n\nRestore "${snap.name}" anyway?`)) return;
  r.furniture = clone(snap.furniture);
  r.groups = clone(snap.groups);
  r.activeSnapshotId = snap.id;
  selection = [];
  commit();
}

// Step to the previous (-1) or next (+1) snapshot, relative to the active one.
function stepSnapshot(dir) {
  const r = currentRoom();
  if (!r || !r.snapshots.length) return;
  const i = r.snapshots.findIndex((s) => s.id === r.activeSnapshotId);
  const next = i < 0 ? (dir > 0 ? 0 : r.snapshots.length - 1) : i + dir;
  if (next >= 0 && next < r.snapshots.length) restoreSnapshot(r.snapshots[next].id);
}

function updateSnapshot(id) {
  const r = currentRoom(), snap = r && findSnapshot(r, id);
  if (!snap || !confirm(`Overwrite "${snap.name}" with the current arrangement?`)) return;
  snap.furniture = clone(r.furniture);
  snap.groups = clone(r.groups);
  snap.createdAt = new Date().toISOString();
  r.activeSnapshotId = snap.id;
  commit();
}

function renameSnapshot(id) {
  const snap = findSnapshot(currentRoom(), id);
  const name = snap && prompt('Snapshot name', snap.name);
  if (!name || !name.trim()) return;
  snap.name = name.trim();
  commit();
}

function deleteSnapshot(id) {
  const r = currentRoom(), snap = r && findSnapshot(r, id);
  if (!snap || !confirm(`Delete snapshot "${snap.name}"? The current arrangement on the plan stays as it is.`)) return;
  r.snapshots = r.snapshots.filter((s) => s !== snap);
  if (r.activeSnapshotId === id) r.activeSnapshotId = null;
  commit();
}

function snapshotThumb(r, snap) {
  const m = 12;
  const body = snap.furniture.map((f) =>
    `<g transform="translate(${f.x} ${f.y}) rotate(${f.rotation})">
      <rect x="${-f.width / 2}" y="${-f.length / 2}" width="${f.width}" height="${f.length}" fill="${f.color}" fill-opacity=".45" stroke="${f.color}" stroke-width="3"/>
      ${drawBands(f, `thumb-${snap.id}-${f.id}`, [`fill="${f.color}"`])}
    </g>`).join('');
  return `<svg class="snap-thumb" viewBox="${-m} ${-m} ${r.width + 2 * m} ${r.length + 2 * m}" aria-hidden="true">
    <rect x="0" y="0" width="${r.width}" height="${r.length}" fill="#fff" stroke="#3a3f47" stroke-width="${m}"/>${body}</svg>`;
}

function renderSnapshots() {
  const r = currentRoom();
  const ul = $('#snapshotList');
  if (!r) { ul.innerHTML = ''; return; }
  const active = findSnapshot(r, r.activeSnapshotId);
  const index = active ? r.snapshots.indexOf(active) : -1;
  $('#prevSnapshotBtn').disabled = !r.snapshots.length || index === 0;
  $('#nextSnapshotBtn').disabled = !r.snapshots.length || index === r.snapshots.length - 1;
  $('#snapshotNav').hidden = r.snapshots.length < 2;

  if (!r.snapshots.length) {
    ul.innerHTML = '<li class="muted">No snapshots yet. Save one to keep this arrangement.</li>';
    return;
  }
  ul.innerHTML = r.snapshots.map((snap) => {
    const current = snapshotMatches(r, snap);
    const isActive = snap === active;
    const badge = current ? '<span class="badge">on plan</span>' : isActive ? '<span class="badge modified">modified</span>' : '';
    return `
      <li data-snap="${snap.id}" class="snap${isActive ? ' active' : ''}" title="Click to restore">
        ${snapshotThumb(r, snap)}
        <div class="snap-main">
          <div class="snap-name">${esc(snap.name)} ${badge}</div>
          <div class="snap-meta">${fmtDate(snap.createdAt)} · ${snap.furniture.length} pieces</div>
        </div>
        <div class="snap-actions">
          <button type="button" data-act="update" title="Overwrite with the current arrangement">⤓</button>
          <button type="button" data-act="rename" title="Rename">✎</button>
          <button type="button" data-act="delete" class="danger" title="Delete">✕</button>
        </div>
      </li>`;
  }).join('');
}

$('#snapshotForm').addEventListener('submit', (e) => { e.preventDefault(); saveSnapshot(); });
$('#prevSnapshotBtn').addEventListener('click', () => stepSnapshot(-1));
$('#nextSnapshotBtn').addEventListener('click', () => stepSnapshot(1));
$('#snapshotList').addEventListener('click', (e) => {
  const li = e.target.closest('li[data-snap]');
  if (!li) return;
  const act = e.target.closest('[data-act]');
  const id = li.dataset.snap;
  if (!act) restoreSnapshot(id);
  else if (act.dataset.act === 'update') updateSnapshot(id);
  else if (act.dataset.act === 'rename') renameSnapshot(id);
  else if (act.dataset.act === 'delete') deleteSnapshot(id);
});

/* ---------- rooms ---------- */

const dialog = $('#roomDialog');

function openRoomDialog(r) {
  const form = $('#roomForm');
  draft = { id: r ? r.id : null, openings: r ? r.openings.map((o) => ({ ...o })) : [] };
  $('#roomDialogTitle').textContent = r ? 'Edit room' : 'New room';
  form.elements.name.value = r ? r.name : `Room ${state.rooms.length + 1}`;
  form.elements.width.value = r ? r.width : 400;
  form.elements.namedItem('length').value = r ? r.length : 350;
  form.elements.height.value = r ? r.height : 250;
  $('#roomError').textContent = '';
  renderOpeningRows();
  dialog.showModal();
}

function openingRowHtml(o, i) {
  const opt = (val, label, cur) => `<option value="${val}"${val === cur ? ' selected' : ''}>${label}</option>`;
  const door = o.type === 'door';
  return `<tr data-idx="${i}">
    <td><select name="type">${opt('door', 'Door', o.type)}${opt('window', 'Window', o.type)}</select></td>
    <td><select name="wall">${['top', 'right', 'bottom', 'left'].map((w) => opt(w, cap(w), o.wall)).join('')}</select></td>
    <td><input name="offset" type="number" min="0" step="1" value="${o.offset}"></td>
    <td><input name="width" type="number" min="1" step="1" value="${o.width}"></td>
    <td><input name="height" type="number" min="1" step="1" value="${o.height}"></td>
    <td>${door ? '—' : `<input name="sill" type="number" min="0" step="1" value="${o.sill}">`}</td>
    <td>${door ? `<select name="hinge">${opt('start', 'Left / top', o.hinge)}${opt('end', 'Right / bottom', o.hinge)}</select>` : '—'}</td>
    <td>${door ? `<select name="swing">${opt('inward', 'Inward', o.swing)}${opt('outward', 'Outward', o.swing)}</select>` : '—'}</td>
    <td><button type="button" class="danger" data-remove title="Remove">✕</button></td>
  </tr>`;
}

function renderOpeningRows() {
  $('#openingRows').innerHTML = draft.openings.map(openingRowHtml).join('');
  $('#noOpenings').hidden = draft.openings.length > 0;
}

function addOpening(type) {
  draft.openings.push({ id: uid(), type, wall: 'top', offset: 30, ...OPENING_DEFAULTS[type] });
  renderOpeningRows();
}

$('#openingRows').addEventListener('input', (e) => {
  const tr = e.target.closest('tr');
  if (!tr) return;
  const o = draft.openings[tr.dataset.idx];
  const { name, value } = e.target;
  if (name === 'type') {
    const { id, wall, offset } = o;
    draft.openings[tr.dataset.idx] = { id, type: value, wall, offset, ...OPENING_DEFAULTS[value] };
    renderOpeningRows();
  } else if (['offset', 'width', 'height', 'sill'].includes(name)) {
    o[name] = num(value, NaN);
  } else {
    o[name] = value;
  }
});

$('#openingRows').addEventListener('click', (e) => {
  if (!e.target.closest('[data-remove]')) return;
  draft.openings.splice(e.target.closest('tr').dataset.idx, 1);
  renderOpeningRows();
});

function validateRoom(width, length, height, openings) {
  if (!(width > 0 && length > 0 && height > 0)) return 'Width, length and ceiling height must be positive numbers.';
  const label = (o, i) => `${cap(o.type)} ${i + 1}`;
  for (const [i, o] of openings.entries()) {
    const wallLen = o.wall === 'top' || o.wall === 'bottom' ? width : length;
    if (!(o.width > 0) || !(o.height > 0) || !(o.offset >= 0)) return `${label(o, i)}: offset, width and height must be filled in.`;
    if (o.offset + o.width > wallLen) return `${label(o, i)} doesn't fit on the ${o.wall} wall (${o.offset} + ${o.width} cm > ${wallLen} cm).`;
    if (o.type === 'window' && !(o.sill >= 0)) return `${label(o, i)}: sill height must be filled in.`;
    if (o.height + (o.type === 'window' ? o.sill : 0) > height) return `${label(o, i)} reaches higher than the ceiling.`;
    for (const [j, p] of openings.entries()) {
      if (j > i && p.wall === o.wall && o.offset < p.offset + p.width && p.offset < o.offset + o.width) {
        return `${label(o, i)} and ${label(p, j)} overlap on the ${o.wall} wall.`;
      }
    }
  }
  return null;
}

$('#roomForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const name = fd.get('name').trim() || 'Room';
  const width = num(fd.get('width')), length = num(fd.get('length')), height = num(fd.get('height'));
  const error = validateRoom(width, length, height, draft.openings);
  if (error) { $('#roomError').textContent = error; return; }

  const existing = state.rooms.find((r) => r.id === draft.id);
  if (existing) {
    Object.assign(existing, { name, width, length, height, openings: draft.openings });
  } else {
    const r = { id: uid(), name, width, length, height, openings: draft.openings, furniture: [], groups: [], snapshots: [] };
    state.rooms.push(r);
    state.currentRoomId = r.id;
    selection = [];
  }
  dialog.close();
  commit();
});

$('#cancelRoomBtn').addEventListener('click', () => dialog.close());
$('#addDoorBtn').addEventListener('click', () => addOpening('door'));
$('#addWindowBtn').addEventListener('click', () => addOpening('window'));
$('#newRoomBtn').addEventListener('click', () => openRoomDialog(null));
$('#emptyNewRoomBtn').addEventListener('click', () => openRoomDialog(null));
$('#editRoomBtn').addEventListener('click', () => openRoomDialog(currentRoom()));

$('#deleteRoomBtn').addEventListener('click', () => {
  const r = currentRoom();
  if (!r || !confirm(`Delete "${r.name}" and all its furniture?`)) return;
  state.rooms = state.rooms.filter((x) => x !== r);
  state.currentRoomId = state.rooms[0] ? state.rooms[0].id : null;
  selection = [];
  commit();
});

$('#roomSelect').addEventListener('change', (e) => {
  state.currentRoomId = e.target.value;
  selection = [];
  commit();
});

/* ---------- options ---------- */

$('#snapToggle').addEventListener('change', (e) => { state.snap = e.target.checked; commit(); });
$('#gridToggle').addEventListener('change', (e) => { state.showGrid = e.target.checked; commit(); });

restorePanels();

loadState().then((loaded) => {
  state = loaded;
  document.body.classList.remove('loading');
  render();
});
