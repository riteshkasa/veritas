import { CAPTIONS_WS } from "../lib/config.js";
import { MSG } from "../lib/messages.js";

// One state object per active tab.
const tabs = new Map(); // tabId -> { sessionId, videoId, capWs }

function getState(tabId) {
  let s = tabs.get(tabId);
  if (!s) {
    s = { sessionId: crypto.randomUUID(), videoId: "", capWs: null, meta: null };
    tabs.set(tabId, s);
  }
  return s;
}

function sendToTab(tabId, payload) {
  chrome.tabs.sendMessage(tabId, payload).catch(() => {});
}

function attachWsHandlers(ws, tabId) {
  ws.addEventListener("message", (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    if (data.type === "verdict") sendToTab(tabId, { type: MSG.VERDICT, payload: data });
    else if (data.type === "transcript") sendToTab(tabId, { type: MSG.TRANSCRIPT, payload: data });
    else if (data.type === "status") sendToTab(tabId, { type: MSG.STATUS, payload: data });
  });
  ws.addEventListener("close", () => {
    sendToTab(tabId, { type: MSG.STATUS, payload: { type: "status", level: "warn", message: "Captions N/A" } });
  });
  ws.addEventListener("error", () => {
    sendToTab(tabId, { type: MSG.STATUS, payload: { type: "status", level: "error", message: "Captions Error" } });
  });
}

async function ensureCaptionsWs(tabId, videoId, meta) {
  const s = getState(tabId);
  s.videoId = videoId || s.videoId;
  if (meta) s.meta = meta;
  if (s.capWs && s.capWs.readyState === WebSocket.OPEN) return s.capWs;
  const ws = new WebSocket(CAPTIONS_WS);
  s.capWs = ws;
  await new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true });
    ws.addEventListener("error", rej, { once: true });
  });
  ws.send(JSON.stringify({
    type: "hello",
    sessionId: s.sessionId,
    videoId: s.videoId,
    meta: s.meta || {},
  }));
  attachWsHandlers(ws, tabId);
  return ws;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    const tabId = sender?.tab?.id;
    try {
      if (msg.type === MSG.START) {
        await ensureCaptionsWs(tabId, msg.payload?.videoId || "", msg.payload?.meta);
        sendResponse({ ok: true });
      } else if (msg.type === MSG.STOP) {
        const s = tabs.get(tabId);
        if (s) {
          if (s.capWs) try { s.capWs.close(); } catch {}
          tabs.delete(tabId);
        }
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
      } else {
        sendResponse({ ok: false, error: "unknown" });
      }
    } catch (e) {
      console.error("[niwas bg]", e);
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  const s = tabs.get(tabId);
  if (!s) return;
  try { s.capWs && s.capWs.close(); } catch {}
  tabs.delete(tabId);
});
