// Falling-note piano visualizer on a <canvas>, colored per MIDI track.
// Key geometry comes from the backend (Api.get_piano_layout, the tested
// utils.piano_layout math), normalized to width 1.0.

import { darker, lighter, noteColor, rgba } from "./color.js";

const KEYBOARD_HEIGHT_RATIO = 0.22;
const LOOKAHEAD_SECONDS = 3.0;
const MIN_BAR_HEIGHT = 3;
const BAR_MARGIN_RATIO = 0.12;
const BAR_CORNER_RADIUS = 5;
const KEY_CORNER_RADIUS = 3;
const BLACK_KEY_HEIGHT_RATIO = 0.62;
const HIT_LINE_HEIGHT = 3;
const GRID_STEP_SECONDS = 0.5;
const NOTE_MIN = 21;
const NOTE_MAX = 108;

const OUT_OF_RANGE_ALPHA = 0.35;
const OUT_OF_RANGE_KEY_SHADE = "rgba(0, 0, 0, 0.55)";

const clampNote = (note) => Math.max(NOTE_MIN, Math.min(NOTE_MAX, note));

/** Mirrors utils.wwm_macro.fold_note: shift by octaves into [low, high]. */
function foldNote(note, low, high) {
  while (note < low) note += 12;
  while (note > high) note -= 12;
  return note;
}

/** Index of the first element of sorted `values` that is >= target. */
function bisectLeft(values, target) {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (values[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export class Visualizer {
  constructor(canvas, layout) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.layout = layout.map(([note, x, width, white]) => ({ note, x, width, white }));
    this.byNote = new Map(this.layout.map((key) => [key.note, key]));
    this.skin = null;
    this.palette = null;
    this.muted = new Set();
    this.range = null;
    this.clear();
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.resize();
  }

  /** notes: [[start, end, note, track, isDrum], ...], sorted by start. */
  load(notes) {
    this.notes = notes;
    this.starts = notes.map((n) => n[0]);
    this.maxDuration = notes.reduce((max, n) => Math.max(max, n[1] - n[0]), 0);
    this.tracks = new Set(notes.map((n) => n[3]));
  }

  clear() {
    this.load([]);
  }

  setMuted(tracks) {
    this.muted = new Set(tracks);
  }

  /** [low, high] playable in WWM mode (out-of-range notes get octave-folded), or null to hide. */
  setRange(range) {
    this.range = range;
  }

  setSkin(skin, palette) {
    this.skin = skin;
    this.palette = palette;
  }

  resize() {
    const ratio = window.devicePixelRatio || 1;
    this.width = this.canvas.clientWidth;
    this.height = this.canvas.clientHeight;
    this.canvas.width = Math.round(this.width * ratio);
    this.canvas.height = Math.round(this.height * ratio);
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  /** Notes overlapping the lookahead window (see PianoVisualizer.__visible_events). */
  visible(position) {
    const windowStart = position - 0.5;
    const windowEnd = position + LOOKAHEAD_SECONDS;
    const visible = [];
    for (let i = bisectLeft(this.starts, windowStart - this.maxDuration); i < this.notes.length; i++) {
      const note = this.notes[i];
      if (note[0] > windowEnd) break;
      if (!this.muted.has(note[3]) && note[1] >= windowStart) visible.push(note);
    }
    return visible;
  }

  /** Draw one frame at `position` seconds; returns live stats for the HUD readouts. */
  render(position) {
    if (!this.palette || !this.width) return { voices: 0, density: 0, tracks: 0 };
    const { ctx, width, height, palette, skin } = this;
    const keyboardHeight = height * KEYBOARD_HEIGHT_RATIO;
    const fallHeight = height - keyboardHeight;
    const background = ctx.createLinearGradient(0, 0, 0, height);
    background.addColorStop(0, palette.BACKGROUND);
    background.addColorStop(1, palette.BACKGROUND_1);
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, width, height);
    const visible = this.visible(position);
    const sounding = new Map();
    for (const [start, end, note, track, isDrum] of visible) {
      if (start <= position && position <= end) {
        sounding.set(clampNote(note), noteColor(skin.note_colors, track, isDrum));
      }
    }
    if (skin.hud) this.drawGrid(position, fallHeight);
    this.drawNotes(visible, position, fallHeight);
    this.drawHitLine(fallHeight);
    this.drawKeyboard(fallHeight, keyboardHeight, sounding);
    if (this.range) this.drawRange(visible, position, fallHeight, keyboardHeight);
    const recent = bisectLeft(this.starts, position + 1e-9) - bisectLeft(this.starts, position - 1);
    const tracks = [...this.tracks].filter((t) => !this.muted.has(t)).length;
    return { voices: sounding.size, density: recent, tracks };
  }

  drawGrid(position, fallHeight) {
    const { ctx, width } = this;
    const pixelsPerSecond = fallHeight / LOOKAHEAD_SECONDS;
    ctx.lineWidth = 1;
    ctx.strokeStyle = rgba(this.palette.BORDER, 90 / 255);
    ctx.beginPath();
    for (const key of this.layout) {
      if (key.note % 12 === 0) {
        const x = Math.round(key.x * width) + 0.5;
        ctx.moveTo(x, 0);
        ctx.lineTo(x, fallHeight);
      }
    }
    ctx.stroke();
    const first = Math.ceil(position / GRID_STEP_SECONDS);
    const last = Math.floor((position + LOOKAHEAD_SECONDS) / GRID_STEP_SECONDS);
    for (let step = first; step <= last; step++) {
      const y = Math.round(fallHeight - (step * GRID_STEP_SECONDS - position) * pixelsPerSecond) + 0.5;
      ctx.strokeStyle = rgba(this.palette.BORDER, (step % 2 === 0 ? 200 : 90) / 255);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
  }

  drawNotes(visible, position, fallHeight) {
    const { ctx, width, skin } = this;
    const pixelsPerSecond = fallHeight / LOOKAHEAD_SECONDS;
    for (const [start, end, note, track, isDrum] of visible) {
      const key = this.byNote.get(clampNote(note));
      const keyX = key.x * width;
      const keyWidth = key.width * width;
      let top = Math.max(fallHeight - (end - position) * pixelsPerSecond, 0);
      let bottom = Math.min(fallHeight - (start - position) * pixelsPerSecond, fallHeight);
      if (bottom - top < MIN_BAR_HEIGHT) bottom = top + MIN_BAR_HEIGHT;
      const margin = Math.max(1, keyWidth * BAR_MARGIN_RATIO);
      const x = keyX + margin;
      const barWidth = keyWidth - margin * 2;
      const color = noteColor(skin.note_colors, track, isDrum);
      const radius = Math.min(BAR_CORNER_RADIUS, skin.radius_sm, barWidth / 2);
      const gradient = ctx.createLinearGradient(0, top, 0, bottom);
      gradient.addColorStop(0, darker(color, 125));
      gradient.addColorStop(1, lighter(color, 135));
      // Only sounding notes glow: haloing every falling bar is the costliest
      // part of a frame on dense songs, and glow reads best as "being hit".
      const glowing = skin.neon_glow && start <= position && position <= end;
      const folded = this.range && (note < this.range[0] || note > this.range[1]);
      ctx.globalAlpha = folded ? OUT_OF_RANGE_ALPHA : 1;
      ctx.setLineDash(folded ? [3, 3] : []);
      ctx.shadowBlur = glowing ? 14 : 0;
      ctx.shadowColor = glowing ? color : "transparent";
      ctx.fillStyle = gradient;
      ctx.strokeStyle = lighter(color, 160);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(x, top, barWidth, bottom - top, radius);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
  }

  /**
   * WWM playable range: dim the keys the game can't play, mark the playable
   * span above the keyboard, and outline the key each sounding out-of-range
   * note actually gets folded onto.
   */
  drawRange(visible, position, top, keyboardHeight) {
    const { ctx, width, palette } = this;
    const [low, high] = this.range;
    const left = this.byNote.get(low).x * width;
    const highKey = this.byNote.get(high);
    const right = (highKey.x + highKey.width) * width;
    ctx.fillStyle = OUT_OF_RANGE_KEY_SHADE;
    ctx.fillRect(0, top, left, keyboardHeight);
    ctx.fillRect(right, top, width - right, keyboardHeight);
    ctx.fillStyle = palette.HIGHLIGHT;
    ctx.fillRect(left, top - 1, right - left, 2);
    ctx.lineWidth = 2;
    for (const [start, end, note, track, isDrum] of visible) {
      if (start > position || position > end || (note >= low && note <= high)) continue;
      const key = this.byNote.get(foldNote(note, low, high));
      const height = key.white ? keyboardHeight : keyboardHeight * BLACK_KEY_HEIGHT_RATIO;
      ctx.strokeStyle = noteColor(this.skin.note_colors, track, isDrum);
      ctx.strokeRect(key.x * width + 2, top + 2, key.width * width - 4, height - 4);
    }
  }

  drawHitLine(fallHeight) {
    const { ctx, width, palette } = this;
    ctx.shadowBlur = this.skin.neon_glow ? 12 : 0;
    ctx.shadowColor = palette.ACCENT_1;
    ctx.fillStyle = rgba(palette.ACCENT_1, 160 / 255);
    ctx.fillRect(0, fallHeight - HIT_LINE_HEIGHT, width, HIT_LINE_HEIGHT);
    ctx.shadowBlur = 0;
  }

  drawKeyboard(top, keyboardHeight, sounding) {
    const { ctx, width, skin, palette } = this;
    const piano = skin.piano;
    const radius = Math.min(KEY_CORNER_RADIUS, skin.radius_sm);
    const drawKey = (key, height, colors, stroke) => {
      const x = key.x * width;
      const gradient = ctx.createLinearGradient(0, top, 0, top + height);
      gradient.addColorStop(0, colors[0]);
      gradient.addColorStop(1, colors[1]);
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.roundRect(x, top, key.width * width, height, radius);
      ctx.fill();
      if (stroke) {
        ctx.strokeStyle = stroke;
        ctx.stroke();
      }
    };
    for (const key of this.layout) {
      if (!key.white) continue;
      const glow = sounding.get(key.note);
      drawKey(key, keyboardHeight,
        glow ? [lighter(glow, 150), glow] : [piano.white_top, piano.white_bottom],
        piano.border || palette.BACKGROUND);
    }
    for (const key of this.layout) {
      if (key.white) continue;
      const glow = sounding.get(key.note);
      drawKey(key, keyboardHeight * BLACK_KEY_HEIGHT_RATIO,
        glow ? [lighter(glow, 140), darker(glow, 110)] : [piano.black_top, piano.black_bottom],
        piano.border);
    }
  }
}
