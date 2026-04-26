// Content script. Runs as a classic (non-module) script per manifest, so we
// inline everything we need rather than `import`. Communicates with the
// background service worker via chrome.runtime messaging.

(() => {
  const MSG = {
    START: "niwas/start",
    STOP: "niwas/stop",
    CC_CUE: "niwas/cc-cue",
    CHAT: "niwas/chat",
    VERDICT: "niwas/verdict",
    STATUS: "niwas/status",
    TRANSCRIPT: "niwas/transcript",
    CHAT_RESPONSE: "niwas/chat-response",
  };

  const state = {
    enabled: false,
    ccObserver: null,
    lastCueText: "",
    lastCueAt: 0,
  };

  // ----- video helpers -----
  function getVideo() {
    return document.querySelector("video");
  }
  function getVideoId() {
    const u = new URL(location.href);
    return u.searchParams.get("v") || location.pathname.split("/").pop() || "";
  }
  function getVideoTimeMs() {
    const v = getVideo();
    return v ? Math.floor(v.currentTime * 1000) : 0;
  }
  function getVideoMeta() {
    const title = document.querySelector(
      "yt-formatted-string.style-scope.ytd-watch-metadata, h1.ytd-video-primary-info-renderer yt-formatted-string"
    )?.textContent?.trim() || document.title.replace(" - YouTube", "").trim();
    const channel = document.querySelector(
      "ytd-channel-name yt-formatted-string a, #channel-name a"
    )?.textContent?.trim() || "";
    const desc = document.querySelector(
      "ytd-text-inline-expander .content, #description-inline-expander yt-attributed-string span"
    )?.textContent?.trim().slice(0, 500) || "";
    const dateEl = document.querySelector(
      "#info-strings yt-formatted-string, ytd-video-primary-info-renderer .date"
    );
    const publishDate = dateEl?.textContent?.trim() || "";
    return { title, channel, description: desc, publishDate };
  }

  // ----- overlay UI -----
  const overlay = document.createElement("div");
  overlay.id = "niwas-overlay";
  overlay.innerHTML = `
    <div class="niwas-header">
      <span class="niwas-title">Veritas</span>
      <span class="niwas-badge" id="niwas-badge" title="Verdicts">0</span>
      <span class="niwas-status" id="niwas-status">idle</span>
      <button class="niwas-btn" id="niwas-toggle">Start</button>
      <button class="niwas-btn niwas-btn-ghost" id="niwas-collapse" title="Expand / Collapse">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
    </div>
    <div class="niwas-body" id="niwas-body">
      <div class="niwas-section niwas-section-facts">
        <div class="niwas-section-label">Fact Check</div>
        <div class="niwas-list" id="niwas-list"></div>
      </div>
      <div class="niwas-split-handle" id="niwas-split-handle"><div class="niwas-split-grip"></div></div>
      <div class="niwas-section niwas-section-chat">
        <div class="niwas-section-label">Ask Veritas</div>
        <div class="niwas-chat" id="niwas-chat"></div>
        <div class="niwas-chat-input-row">
          <input type="text" id="niwas-chat-input" class="niwas-chat-input" placeholder="Ask a question…" />
          <button id="niwas-chat-send" class="niwas-btn niwas-chat-send-btn" title="Send">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </div>
    </div>
    <div class="niwas-resize" id="niwas-resize"></div>
  `;
  document.documentElement.appendChild(overlay);

  const $status = overlay.querySelector("#niwas-status");
  const $toggle = overlay.querySelector("#niwas-toggle");
  const $collapse = overlay.querySelector("#niwas-collapse");
  const $body = overlay.querySelector("#niwas-body");
  const $list = overlay.querySelector("#niwas-list");
  const $chatArea = overlay.querySelector("#niwas-chat");
  const $chatInput = overlay.querySelector("#niwas-chat-input");
  const $chatSend = overlay.querySelector("#niwas-chat-send");

  let collapsed = false;
  const $badge = overlay.querySelector("#niwas-badge");
  function setCollapsed(val) {
    collapsed = val;
    overlay.classList.toggle("niwas-collapsed", collapsed);
  }
  $collapse.addEventListener("click", () => setCollapsed(!collapsed));

  // ----- split-handle: drag to resize facts vs chat sections -----
  (function makeSplitResizable() {
    const handle = overlay.querySelector("#niwas-split-handle");
    const factsSection = overlay.querySelector(".niwas-section-facts");
    const body = overlay.querySelector("#niwas-body");
    let dragging = false, startY = 0, startFactsH = 0;
    handle.addEventListener("mousedown", (e) => {
      dragging = true;
      startY = e.clientY;
      startFactsH = factsSection.getBoundingClientRect().height;
      document.body.style.userSelect = "none";
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const dy = e.clientY - startY;
      const bodyH = body.getBoundingClientRect().height;
      // facts can be 40px...(bodyH - 100px), leaving room for chat
      const newFacts = Math.min(bodyH - 100, Math.max(40, startFactsH + dy));
      factsSection.style.flex = "0 0 " + newFacts + "px";
    });
    window.addEventListener("mouseup", () => {
      if (dragging) document.body.style.userSelect = "";
      dragging = false;
    });
  })();

  // ----- chat helpers -----
  function sendChat() {
    const text = ($chatInput.value || "").trim();
    if (!text) return;
    appendChatBubble(text, "user");
    $chatInput.value = "";
    $chatInput.disabled = true;
    $chatSend.disabled = true;
    chrome.runtime.sendMessage({
      type: MSG.CHAT,
      payload: { videoId: getVideoId(), text },
    }).catch(() => {});
  }
  function appendChatBubble(text, role) {
    const bubble = document.createElement("div");
    bubble.className = `niwas-chat-bubble niwas-chat-${role}`;
    bubble.textContent = text;
    $chatArea.appendChild(bubble);
    while ($chatArea.childElementCount > 60) $chatArea.removeChild($chatArea.firstChild);
    $chatArea.scrollTop = $chatArea.scrollHeight;
  }
  $chatSend.addEventListener("click", sendChat);
  // Stop YouTube from capturing keyboard events inside the chat input.
  ["keydown", "keyup", "keypress"].forEach((evt) => {
    $chatInput.addEventListener(evt, (e) => e.stopPropagation());
  });
  $chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });

  // resize handle
  (function makeResizable() {
    const handle = overlay.querySelector("#niwas-resize");
    let resizing = false, startY = 0, startH = 0;
    handle.addEventListener("mousedown", (e) => {
      resizing = true;
      startY = e.clientY;
      startH = overlay.offsetHeight;
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!resizing) return;
      const newH = Math.max(80, startH + (e.clientY - startY));
      overlay.style.maxHeight = newH + "px";
    });
    window.addEventListener("mouseup", () => { resizing = false; });
  })();

  // draggable
  (function makeDraggable() {
    const header = overlay.querySelector(".niwas-header");
    let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
    header.addEventListener("mousedown", (e) => {
      if (e.target.tagName === "BUTTON") return;
      dragging = true;
      sx = e.clientX; sy = e.clientY;
      const r = overlay.getBoundingClientRect();
      ox = r.left; oy = r.top;
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      overlay.style.left = `${ox + (e.clientX - sx)}px`;
      overlay.style.top = `${oy + (e.clientY - sy)}px`;
      overlay.style.right = "auto";
    });
    window.addEventListener("mouseup", () => { dragging = false; });
  })();

  $toggle.addEventListener("click", async () => {
    if (state.enabled) await stop(); else await start();
  });

  function setStatus(text, level = "info") {
    $status.textContent = text;
    $status.dataset.level = level;
  }

  function renderVerdict(v) {
    const card = document.createElement("div");
    card.className = `niwas-card niwas-${v.verdict}`;
    const conf = Math.round((v.confidence ?? 0) * 100);
    const time = msToClock(v.video_time_ms || 0);
    const cites = (v.citations || []).map(c =>
      `<a href="${escapeAttr(c.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(c.title || c.url)}</a>`
    ).join(" · ");
    card.innerHTML = `
      <div class="niwas-card-head">
        <span class="niwas-verdict">${v.verdict}</span>
        <span class="niwas-conf">${conf}%</span>
        <span class="niwas-time" data-t="${v.video_time_ms || 0}">${time}</span>
      </div>
      <div class="niwas-claim">${escapeHtml(v.claim || "")}</div>
      ${v.rationale ? `<div class="niwas-rationale">${escapeHtml(v.rationale)}</div>` : ""}
      ${cites ? `<div class="niwas-cites">${cites}</div>` : ""}
    `;
    card.querySelector(".niwas-time").addEventListener("click", () => {
      const v2 = getVideo();
      if (v2 && Number.isFinite(+card.querySelector(".niwas-time").dataset.t)) {
        v2.currentTime = (+card.querySelector(".niwas-time").dataset.t) / 1000;
      }
    });
    $list.prepend(card);
    while ($list.childElementCount > 50) $list.removeChild($list.lastChild);
    $badge.textContent = $list.childElementCount;
  }

  function msToClock(ms) {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    return `${m}:${String(s % 60).padStart(2, "0")}`;
  }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
  function escapeAttr(s) { return escapeHtml(s); }

  // ----- caption observer -----
  // YouTube reveals captions progressively (word-by-word) within a single cue,
  // then replaces the entire cue when the next one starts. We want to send
  // each cue exactly once, when it FINALIZES — either because a new cue
  // replaces it, or because the text has been stable for IDLE_MS.
  const FINALIZE_IDLE_MS = 1400;

  function startCaptionObserver() {
    stopCaptionObserver();
    let activeText = "";
    let activeStartMs = 0;
    let lastEmitted = "";
    let idleTimer = null;

    const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
    const isExtension = (prev, next) =>
      next === prev || next.startsWith(prev) || prev.startsWith(next);

    function emitActive() {
      const text = activeText;
      if (!text || text === lastEmitted) return;
      lastEmitted = text;
      chrome.runtime.sendMessage({
        type: MSG.CC_CUE,
        payload: {
          videoId: getVideoId(),
          startMs: activeStartMs,
          endMs: getVideoTimeMs(),
          text,
        },
      }).catch(() => {});
    }
    function scheduleIdleFinalize() {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => emitActive(), FINALIZE_IDLE_MS);
    }

    const tick = () => {
      const segs = document.querySelectorAll(".ytp-caption-segment");
      const text = norm(Array.from(segs).map((s) => s.textContent || "").join(" "));
      if (!text) {
        // Caption disappeared -> finalize whatever was active.
        if (activeText) {
          emitActive();
          activeText = "";
        }
        return;
      }
      if (text === activeText) return;
      if (activeText && !isExtension(activeText, text)) {
        // A new cue has replaced the old one.
        emitActive();
        activeText = text;
        activeStartMs = getVideoTimeMs();
      } else if (!activeText) {
        activeText = text;
        activeStartMs = getVideoTimeMs();
      } else {
        // Same cue, just grew (or shrank). Keep accumulating; pick whichever
        // is longer so we don't lose any words.
        activeText = text.length >= activeText.length ? text : activeText;
      }
      // Track the latest known timestamps too.
      state.lastCueText = activeText;
      state.lastCueAt = performance.now();
      scheduleIdleFinalize();
    };

    const container = document.querySelector(".ytp-caption-window-container") || document.body;
    const obs = new MutationObserver(tick);
    obs.observe(container, { childList: true, subtree: true, characterData: true });
    state.ccObserver = obs;
    state._ccCleanup = () => { if (idleTimer) clearTimeout(idleTimer); };
  }

  function stopCaptionObserver() {
    if (state.ccObserver) { state.ccObserver.disconnect(); state.ccObserver = null; }
    if (state._ccCleanup) { state._ccCleanup(); state._ccCleanup = null; }
  }

  // ----- start/stop -----
  async function start() {
    state.enabled = true;
    $toggle.textContent = "Stop";
    setStatus("Starting…");

    // Try to enable YouTube subtitles button if it's off.
    const ccBtn = document.querySelector(".ytp-subtitles-button");
    if (ccBtn && ccBtn.getAttribute("aria-pressed") === "false") {
      try { ccBtn.click(); } catch {}
    }

    await sendBg({ type: MSG.START, payload: { videoId: getVideoId(), meta: getVideoMeta() } });
    startCaptionObserver();
    setStatus("Watching Captions…");
  }

  async function stop() {
    state.enabled = false;
    $toggle.textContent = "Start";
    stopCaptionObserver();
    await sendBg({ type: MSG.STOP });
    setStatus("Stopped");
  }

  function sendBg(msg) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (resp) => resolve(resp));
      } catch { resolve(null); }
    });
  }

  // ----- inbound messages -----
  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg || !msg.type) return;
    if (msg.type === MSG.VERDICT) renderVerdict(msg.payload);
    else if (msg.type === MSG.STATUS) setStatus(msg.payload.message, msg.payload.level || "info");
    else if (msg.type === MSG.CHAT_RESPONSE) {
      appendChatBubble(msg.payload.text, "assistant");
      $chatInput.disabled = false;
      $chatSend.disabled = false;
      $chatInput.focus();
    }
    else if (msg.type === "niwas/popup-toggle") {
      if (msg.action === "start" && !state.enabled) start();
      else if (msg.action === "stop" && state.enabled) stop();
    }
  });

  // Stop when navigating away from a watch page.
  let lastHref = location.href;
  setInterval(() => {
    if (location.href !== lastHref) {
      lastHref = location.href;
      if (state.enabled) stop();
      $list.innerHTML = "";
      $chatArea.innerHTML = "";
    }
  }, 1000);

  setStatus("Idle");
})();
