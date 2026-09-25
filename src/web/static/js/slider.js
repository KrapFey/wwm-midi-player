// Click/drag slider shared by the progress bar and volume control. Its look -
// smooth pill vs. segmented LED bar - is entirely up to the skin's CSS.

export class Slider {
  /**
   * @param {HTMLElement} element  a .slider element (with .slider-fill/.slider-thumb children)
   * @param {object} options  {max, onInput(value), onCommit(value), onHover(value, x) - value
   *   null when the pointer leaves}
   */
  constructor(element, { max = 1, onInput = () => {}, onCommit = () => {}, onHover = () => {} } = {}) {
    this.element = element;
    this.max = max;
    this.value = 0;
    this.dragging = false;
    element.addEventListener("pointerdown", (event) => {
      this.dragging = true;
      element.classList.add("dragging");
      element.setPointerCapture(event.pointerId);
      onInput(this.setFromPointer(event));
    });
    element.addEventListener("pointermove", (event) => {
      if (this.dragging) onInput(this.setFromPointer(event));
      const [value, x] = this.pointerValue(event);
      onHover(value, x);
    });
    element.addEventListener("pointerleave", () => {
      if (!this.dragging) onHover(null, 0);
    });
    element.addEventListener("pointerup", (event) => {
      if (!this.dragging) return;
      this.dragging = false;
      element.classList.remove("dragging");
      onCommit(this.setFromPointer(event));
      if (!element.matches(":hover")) onHover(null, 0);
    });
  }

  /** [value, x offset within the slider] under the pointer. */
  pointerValue(event) {
    const rect = this.element.getBoundingClientRect();
    const x = Math.min(rect.width, Math.max(0, event.clientX - rect.left));
    return [(x / rect.width) * this.max, x];
  }

  setFromPointer(event) {
    this.render(this.pointerValue(event)[0]);
    return this.value;
  }

  /** Programmatic update; ignored mid-drag so playback doesn't fight the user. */
  set(value) {
    if (!this.dragging) this.render(value);
  }

  render(value) {
    this.value = value;
    const fraction = this.max > 0 ? Math.min(1, Math.max(0, value / this.max)) : 0;
    this.element.style.setProperty("--value", fraction.toFixed(4));
  }
}
