import "@testing-library/jest-dom/vitest";

import { afterEach, beforeEach, vi } from "vitest";

// jsdom installs its own DOM `AbortController`/`AbortSignal` globals, but the test runtime keeps
// undici's global `Request`. undici's `Request` rejects the jsdom signal with
// "Expected signal to be an instance of AbortSignal", which breaks React Router v7 navigation
// (it constructs a `Request` with an abort signal). Tests do not rely on request cancellation, so
// we drop an incompatible `signal` from `RequestInit` before delegating to the real constructor.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init && "signal" in init) {
      const rest = { ...init };
      delete (rest as { signal?: unknown }).signal;
      super(input, rest);
    } else {
      super(input, init);
    }
  }
}
globalThis.Request = TestRequest as typeof Request;

// Newer Node releases expose an incomplete experimental global localStorage unless started with a
// backing-file flag, which can shadow jsdom's storage. Keep browser-storage tests deterministic.
if (!window.localStorage) {
  const values = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
}

// jsdom does not implement `Element.prototype.scrollTo` (every real browser does). Source-pane
// active-anchor scrolling calls it directly on its own scroll container (see
// ReviewerWorkspacePage.tsx SourcePane) instead of `scrollIntoView`, precisely to avoid WebKit's
// scrollIntoView walking and repositioning every scrollable ancestor. Stub it as a no-op so that
// code path can mount under jsdom; individual tests may still override/spy on it.
const elementProto = Element.prototype as { scrollTo?: (options?: unknown) => void };
if (typeof elementProto.scrollTo !== "function") {
  elementProto.scrollTo = function scrollTo() {};
}

// Keep the auth bootstrap hermetic: `AuthProvider` calls `/auth/me` on mount. Default every request
// to an unauthenticated response so no test reaches the network. Individual tests can override
// `global.fetch` when they need a specific API response.
beforeEach(() => {
  // Return a fresh Response per call: a Response body can be read only once, and the auth bootstrap
  // may issue several requests per mount (and several mounts per test).
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ detail: "unauthenticated" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});
