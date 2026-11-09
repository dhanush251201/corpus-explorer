// Runtime settings for the Corpus Explorer frontend.
//
// This file is copied unchanged into the build (dist/config.js) and loaded
// before the app, so it can be edited on the server without rebuilding.
//
// apiBase: where the backend API lives - scheme, host and port, no trailing
// slash and no /api suffix, e.g. "https://api.explorer.example.org".
// Leave it empty to call the same origin that serves this page (the Vite dev
// and preview servers proxy /api to the backend, and so can nginx).
// The backend's ALLOW_ORIGINS must include the address this page is served from.
window.CORPUS_EXPLORER_CONFIG = {
  apiBase: "",
};
