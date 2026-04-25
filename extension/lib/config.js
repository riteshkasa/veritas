// Shared extension config. Update BACKEND_HOST if the server is not local.
export const BACKEND_HOST = "localhost:8787";
export const CAPTIONS_WS = `ws://${BACKEND_HOST}/ingest/captions`;
export const AUDIO_WS = `ws://${BACKEND_HOST}/ingest/audio`;

// How often the page-injector polls the captions DOM.
export const CC_POLL_MS = 250;
// Audio segment length (ms) when falling back to tabCapture.
export const AUDIO_SEGMENT_MS = 5000;
