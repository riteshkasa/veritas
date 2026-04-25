async function activeTabId() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab && tab.id;
}

document.getElementById("start").addEventListener("click", async () => {
  const id = await activeTabId();
  if (!id) return;
  // Forward by simulating a click on the in-page toggle through messaging.
  chrome.tabs.sendMessage(id, { type: "niwas/popup-toggle", action: "start" }).catch(() => {});
  window.close();
});

document.getElementById("stop").addEventListener("click", async () => {
  const id = await activeTabId();
  if (!id) return;
  chrome.tabs.sendMessage(id, { type: "niwas/popup-toggle", action: "stop" }).catch(() => {});
  window.close();
});
