// Connects the page to its backend.
//
// Inside the app, pywebview injects window.pywebview.api (the Python web.api.Api
// object; every method returns a Promise) and fires "pywebviewready". In a plain
// browser - web/preview.py, for UI development - there is no pywebview, so after
// a short wait the page falls back to the mock backend in mock.js.
//
// Python pushes events by evaluating window.app.onEvent(name, payload).

const PYWEBVIEW_WAIT_MS = 1500;

export function connectBackend(onEvent) {
  window.app = { onEvent };
  return new Promise((resolve) => {
    if (window.pywebview?.api) {
      resolve(window.pywebview.api);
      return;
    }
    window.addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
    setTimeout(async () => {
      if (window.pywebview) return;
      const { createMockApi } = await import("./mock.js");
      resolve(await createMockApi(onEvent));
    }, PYWEBVIEW_WAIT_MS);
  });
}
