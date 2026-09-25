// Local playback clock: animates the position from the last backend snapshot
// ({position, playing}, pushed on changes and resynced every second) instead
// of asking Python every frame. Timing itself always stays in Python - this
// only drives what's drawn.

export class Clock {
  constructor() {
    this.set({ position: 0, playing: false });
  }

  set({ position, playing }) {
    this.base = position;
    this.playing = playing;
    this.at = performance.now();
  }

  /** Current position in seconds, capped at duration once one is known. */
  position(duration) {
    const position = this.playing ? this.base + (performance.now() - this.at) / 1000 : this.base;
    return duration > 0 ? Math.min(position, duration) : position;
  }
}

export function formatTime(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
