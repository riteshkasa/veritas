import { CAPTIONS_WS, AUDIO_WS } from "../lib/config.js";
import { MSG } from "../lib/messages.js";

// One state object per active tab.
const tabs = new Map(); // tabId -> { sessionId, videoId, capWs, audWs, mode }

function getState(tabId) {
  let s = tabs.get(tabId);
  if (!s) {
    s = {
      sessionId: crypto.randomUUID(),
      videoId: "",
      capWs: null,
      audWs: null,
      mode: null, // 'captions' | 'audio'
    };
    tabs.set(tabId, s);
  }
  return s;
}

function sendToTab(tabId, payload) {
  chrome.tabs.sendMessage(tabId, payload).catch(() => {});
}

function attachWsHandlers(ws, tabId, label) {
  ws.addEventListener("message", (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    if (data.type === "verdict") {
      sendToTab(tabId, { type: MSG.VERDICT, payload: data });
    } else if (data.type === "transcript") {
      sendToTab(tabId, { type: MSG.TRANSCRIPT, payload: data });
    } else if (data.type === "status") {
      sendToTab(tabId, { type: MSG.STATUS, payload: data });
    }
  });
  ws.addEventListener("close", () => {
    sendToTab(tabId, { type: MSG.STATUS, payload: { type: "status", level: "warn", message: `${label} ws closed` } });
  });
  ws.addEventListener("error", () => {
    sendToTab(tabId, { type: MSG.STATUS, payload: { type: "status", level: "error", message: `${label} ws error` } });
  });
}

async function ensureCaptionsWs(tabId, videoId) {
  const s = getState(tabId);
  s.videoId = videoId || s.videoId;
  if (s.capWs && s.capWs.readyState === WebSocket.OPEN) return s.capWs;
  const ws = new WebSocket(CAPTIONS_WS);
  s.capWs = ws;
  await new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true });
    ws.addEventListener("error", rej, { once: true });
  });
  ws.send(JSON.stringify({ type: "hello", sessionId: s.sessionId, videoId: s.videoId }));
  attachWsHandlers(ws, tabId, "captions");
  s.mode = "captions";
  return ws;
}

async function ensureAudioWs(tabId, videoId) {
  const s = getState(tabId);
  s.videoId = videoId || s.videoId;
  if (s.audWs && s.audWs.readyState === WebSocket.OPEN) return s.audWs;
  const ws = new WebSocket(AUDIO_WS);
  s.audWs = ws;
  await new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true });
    ws.addEventListener("error", rej, { once: true });
  });
  ws.send(JSON.stringify({
    type: "hello",
    sessionId: s.sessionId,
    videoId: s.videoId,
    codec: "webm",
    sampleRate: 48000,
    mime: "audio/webm;codecs=opus",
  }));
  attachWsHandlers(ws, tabId, "audio");
  s.mode = "audio";
  return ws;
}

// ---------- Offscreen document management ----------
const OFFSCREEN_PATH = "offscreen/offscreen.html";

async function hasOffscreen() {
  if (!chrome.runtime.getContexts) return false;
  const contexts = await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] });
  return contexts && contexts.length > 0;
}

async function ensureOffscreen() {
  if (await hasOffscreen()) return;
  await chrome.offscreen.createDocument({
    url: OFFSCREEN_PATH,
    reasons: ["USER_MEDIA"],
    justification: "Capture tab audio for live transcription and fact checking.",
  });
}

async function startAudioCapture(tabId, videoId) {
  await ensureOffscreen();
  await ensureAudioWs(tabId, videoId);
  const streamId = await new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId: tabId }, (sid) => {
      if (chrome.runtime.lastError || !sid) {
        reject(chrome.runtime.lastError || new Error("no streamId"));
      } else resolve(sid);
    });
  });
  chrome.runtime.sendMessage({
    type: MSG.OFFSCREEN_START,
    payload: { streamId, tabId },
  });
}

async function stopAudioCapture(tabId) {
  chrome.runtime.sendMessage({ type: MSG.OFFSCREEN_STOP, payload: { tabId } });
}

// ---------- Forward messages ----------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    const tabId = sender?.tab?.id;
    try {
      if (msg.type === MSG.START) {
        // mode: 'captions' | 'audio'
        const { mode = "captions", videoId = "" } = msg.payload || {};
        if (mode === "captions") await ensureCaptionsWs(tabId, videoId);
        else await startAudioCapture(tabId, videoId);
        sendResponse({ ok: true });
      } else if (msg.type === MSG.STOP) {
        const s = tabs.get(tabId);
        if (s) {
          if (s.capWs) try { s.capWs.close(); } catch {}
          if (s.audWs) try { s.audWs.close(); } catch {}
          tabs.delete(tabId);
        }
        await stopAudioCapture(tabId);
        sendResponse({ ok: true });
      } else if (msg.type === MSG.CC_CUE) {
        const s = getState(tabId);
        const ws = await ensureCaptionsWs(tabId, msg.payload.videoId);
        ws.send(JSON.stringify({
          type: "cue",
          sessionId: s.sessionId,
          videoId: s.videoId,
          startMs: msg.payload.startMs,
          endMs: msg.payload.endMs,
          text: msg.payload.text,
        }));
        sendResponse({ ok: true });
      } else if (msg.type === MSG.AUDIO_REQUEST) {
        await startAudioCapture(tabId, msg.payload?.videoId || "");
        sendResponse({ ok: true });
      } else if (msg.type === "niwas/audio-segment") {
        // From offscreen document. Forward bytes + meta to backend.
        const { tabId: tid, videoTimeMs, mime, bytes } = msg.payload;
        const ws = await ensureAudioWs(tid, "");
        ws.send(JSON.stringify({ type: "segment_meta", videoTimeMs, mime }));
        // bytes is a regular array (can't send Blob through messaging); convert.
        const u8 = new Uint8Array(bytes);
        ws.send(u8.buffer);
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false, error: "unknown" });
      }
    } catch (e) {
      console.error("[niwas bg]", e);
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true; // async
});

chrome.tabs.onRemoved.addListener((tabId) => {
  const s = tabs.get(tabId);
  if (!s) return;
  try { s.capWs && s.capWs.close(); } catch {}
  try { s.audWs && s.audWs.close(); } catch {}
  tabs.delete(tabId);
});
