// Local playback clock: animates the position from the last backend snapshot
// ({position, playing}, pushed on changes and resynced every second) instead
// of asking Python every frame. Timing itself always stays in Python - this
// only drives what's drawn.

export class Clock {
  constructor() {
    this.version = 0;
    this.set({ position: 0, playing: false });
  }

  set({ position, playing }) {
    this.base = position;
    this.playing = playing;
    this.at = performance.now();
    this.version += 1;
  }

  /**
   * Re-read the backend clock, unless a newer position arrived meanwhile.
   *
   * The request is an async round-trip: if the user seeks or the backend
   * pushes a clock event while it's in flight, applying the (older) answer
   * would snap the bar back to where it was.
   */
  async resync(fetchClock) {
    const version = this.version;
    const snapshot = await fetchClock();
    if (this.version === version) this.set(snapshot);
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
