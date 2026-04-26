import { AUDIO_SEGMENT_MS } from "../lib/config.js";
import { MSG } from "../lib/messages.js";

// Captures a tab's audio via tabCapture and emits self-contained audio
// segments (~AUDIO_SEGMENT_MS each) back to the service worker. To make each
// segment a standalone playable file (not a stream fragment), we restart the
// MediaRecorder for every segment.

let stream = null;
let recorder = null;
let restartTimer = null;
let routedAudio = null; // AudioContext used to keep the user hearing the tab

function pickMime() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];
  for (const m of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "audio/webm";
}

async function blobToBase64(blob) {
  const buf = await blob.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

function startSegment(streamId, sessionId, videoId, tabId) {
  const mime = pickMime();
  const rec = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 64000 });
  const chunks = [];
  const startedAt = performance.now();

  rec.ondataavailable = (ev) => { if (ev.data && ev.data.size) chunks.push(ev.data); };
  rec.onstop = async () => {
    if (!chunks.length) return;
    const blob = new Blob(chunks, { type: mime });
    const b64 = await blobToBase64(blob);
    chrome.runtime.sendMessage({
      type: MSG.AUDIO_SEGMENT,
      payload: {
        sessionId,
        videoId,
        tabId,
        mime,
        approxDurationMs: Math.round(performance.now() - startedAt),
        base64: b64,
      },
    }).catch(() => {});
  };

  rec.start();
  recorder = rec;

  restartTimer = setTimeout(() => {
    try { rec.stop(); } catch {}
    if (stream) startSegment(streamId, sessionId, videoId, tabId);
  }, AUDIO_SEGMENT_MS);
}

async function start({ streamId, sessionId, videoId, tabId }) {
  if (stream) await stop();
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: streamId,
        },
      },
      video: false,
    });
  } catch (e) {
    chrome.runtime.sendMessage({
      type: MSG.OFFSCREEN_ERROR,
      payload: { tabId, error: String(e) },
    }).catch(() => {});
    return;
  }

  // Pipe captured audio to the speakers so the user keeps hearing the tab.
  try {
    routedAudio = new AudioContext();
    const src = routedAudio.createMediaStreamSource(stream);
    src.connect(routedAudio.destination);
  } catch {}

  startSegment(streamId, sessionId, videoId, tabId);
}

async function stop() {
  if (restartTimer) { clearTimeout(restartTimer); restartTimer = null; }
  try { recorder && recorder.stop(); } catch {}
  recorder = null;
  if (stream) {
    for (const t of stream.getTracks()) try { t.stop(); } catch {}
    stream = null;
  }
  if (routedAudio) {
    try { await routedAudio.close(); } catch {}
    routedAudio = null;
  }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || !msg.type) return;
  if (msg.type === MSG.OFFSCREEN_START) start(msg.payload);
  else if (msg.type === MSG.OFFSCREEN_STOP) stop();
});

// Tell the service worker we're alive and listening. The SW waits for this
// before sending OFFSCREEN_START to avoid a creation race.
chrome.runtime.sendMessage({ type: MSG.OFFSCREEN_READY }).catch(() => {});
