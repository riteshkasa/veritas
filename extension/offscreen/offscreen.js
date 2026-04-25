import { MSG } from "../lib/messages.js";
import { AUDIO_SEGMENT_MS } from "../lib/config.js";

// One active capture at a time.
let active = null; // { tabId, stream, recorder, audioCtx, source, dest, intervalId }

async function start({ streamId, tabId }) {
  await stop();
  // Get the captured tab MediaStream.
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  });

  // We must continue playing audio to the user; route through AudioContext.
  const audioCtx = new AudioContext();
  const source = audioCtx.createMediaStreamSource(stream);
  source.connect(audioCtx.destination);

  // Pick a supported MediaRecorder mime.
  const mimeCandidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];
  const mime = mimeCandidates.find((m) => MediaRecorder.isTypeSupported(m)) || "audio/webm";

  // Restart the recorder every AUDIO_SEGMENT_MS to produce self-contained files.
  function startSegment() {
    const rec = new MediaRecorder(stream, { mimeType: mime });
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      try {
        const blob = new Blob(chunks, { type: mime });
        if (!blob.size) return;
        const ab = await blob.arrayBuffer();
        chrome.runtime.sendMessage({
          type: "niwas/audio-segment",
          payload: {
            tabId,
            videoTimeMs: Date.now(), // wall clock fallback; content script could send true video time
            mime,
            bytes: Array.from(new Uint8Array(ab)),
          },
        });
      } catch (e) { console.warn("[offscreen] segment send failed", e); }
    };
    rec.start();
    active.recorder = rec;
  }

  active = { tabId, stream, audioCtx, source, recorder: null, intervalId: null };
  startSegment();
  active.intervalId = setInterval(() => {
    if (!active) return;
    try { active.recorder && active.recorder.stop(); } catch {}
    startSegment();
  }, AUDIO_SEGMENT_MS);
}

async function stop() {
  if (!active) return;
  try { active.intervalId && clearInterval(active.intervalId); } catch {}
  try { active.recorder && active.recorder.state !== "inactive" && active.recorder.stop(); } catch {}
  try { active.stream.getTracks().forEach((t) => t.stop()); } catch {}
  try { active.audioCtx && active.audioCtx.close(); } catch {}
  active = null;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg.type === MSG.OFFSCREEN_START) {
      try { await start(msg.payload); sendResponse({ ok: true }); }
      catch (e) { console.error("[offscreen]", e); sendResponse({ ok: false, error: String(e) }); }
    } else if (msg.type === MSG.OFFSCREEN_STOP) {
      await stop(); sendResponse({ ok: true });
    }
  })();
  return true;
});
