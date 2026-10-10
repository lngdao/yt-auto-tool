(() => {
  "use strict";

  const HOST_ID = "youtube-batch-link-picker-host";
  const CHECKBOX_CLASS = "youtube-batch-link-picker-checkbox";
  const OVERLAY_CLASS = "youtube-batch-link-picker-overlay";
  const PICKED_BADGE_CLASS = "youtube-batch-link-picker-picked-badge";
  const THUMBNAIL_CLASS = "youtube-batch-link-picker-thumbnail";
  const PICKED_STORAGE_KEY = "pickedVideoHistoryV1";
  const PICKED_VIDEO_STORAGE_PREFIX = "pickedVideoV1:";
  const CARD_SELECTOR = [
    "ytd-rich-item-renderer",
    "ytd-grid-video-renderer",
    "ytd-video-renderer",
    "ytd-compact-video-renderer",
    "ytd-rich-grid-media",
    "ytd-rich-grid-slim-media",
    "yt-lockup-view-model"
  ].join(",");
  const LINK_SELECTOR = [
    "a#thumbnail[href]",
    "a[href*='/watch?v=']",
    "a[href*='/shorts/']",
    "a[href*='/live/']"
  ].join(",");
  const selectedVideos = new Map();
  let pickedVideos = new Map();
  let panel = null;
  let scanTimer = 0;
  let historyLoadSucceeded = false;
  let historyLoadPromise = Promise.resolve();

  function isChannelPage() {
    return /^\/(?:@[^/]+|channel\/[^/]+|c\/[^/]+|user\/[^/]+)(?:\/|$)/i.test(location.pathname);
  }

  function videoFromLink(anchor) {
    try {
      const url = new URL(anchor.href, location.href);
      let videoId = null;
      if (url.pathname === "/watch") {
        videoId = url.searchParams.get("v");
      } else {
        const match = url.pathname.match(/^\/(?:shorts|live|embed)\/([A-Za-z0-9_-]{11})(?:\/|$)/);
        videoId = match ? match[1] : null;
      }
      if (!videoId || !/^[A-Za-z0-9_-]{11}$/.test(videoId)) return null;
      return {
        id: videoId,
        url: "https://www.youtube.com/watch?v=" + videoId
      };
    } catch {
      return null;
    }
  }

  function videoTitleFromCard(card, anchor) {
    const titleSelectors = [
      "#video-title",
      "#video-title-link",
      "a.yt-lockup-metadata-view-model__title",
      ".yt-lockup-metadata-view-model__title",
      "h3 a",
      "h3"
    ];
    for (const selector of titleSelectors) {
      const element = card.querySelector(selector);
      const title = element && (
        element.getAttribute("title")
        || element.getAttribute("aria-label")
        || element.textContent
      );
      if (title && title.trim()) return title.replace(/\s+/g, " ").trim();
    }
    const anchorTitle = anchor.getAttribute("title") || anchor.getAttribute("aria-label");
    return anchorTitle && anchorTitle.trim()
      ? anchorTitle.replace(/\s+/g, " ").trim()
      : "Untitled video";
  }

  function createPanel() {
    const host = document.createElement("div");
    host.id = HOST_ID;
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = [
      ":host{all:initial}",
      ".panel{display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:8px;min-width:230px;padding:11px 12px;border:1px solid #405246;border-radius:11px;color:#eff5ec;background:#1d2a23;box-shadow:0 10px 30px #0005;font:13px/1.35 system-ui,sans-serif}",
      ".count,.status{grid-column:1/-1}",
      ".count{color:#b9c8bb;font-size:12px}",
      ".history-count{grid-column:1/-1;color:#9eae9f;font-size:11px}",
      ".status{min-height:15px;color:#b8e48a;font-size:11px}",
      "button{min-height:34px;padding:0 10px;border:1px solid #687965;border-radius:7px;color:#eaf2e7;background:#2b3a30;font:600 11px system-ui,sans-serif;cursor:pointer}",
      "button.copy{grid-column:1/-1;border-color:#a9cd88;color:#23311e;background:#c5e49f}",
      "button.copy-titles{grid-column:1/-1}",
      "button:hover:not(:disabled){filter:brightness(1.08)}",
      "button:disabled{opacity:.48;cursor:not-allowed}"
    ].join("");
    shadow.append(style);

    const section = document.createElement("section");
    section.className = "panel";
    section.setAttribute("aria-label", "YouTube video link picker");

    const count = document.createElement("div");
    count.className = "count";
    count.setAttribute("aria-live", "polite");

    const historyCount = document.createElement("div");
    historyCount.className = "history-count";

    const selectVisibleButton = document.createElement("button");
    selectVisibleButton.type = "button";
    selectVisibleButton.textContent = "Select visible";

    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.textContent = "Clear";

    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "copy";
    copyButton.textContent = "Copy links";
    copyButton.disabled = true;

    const copyTitlesButton = document.createElement("button");
    copyTitlesButton.type = "button";
    copyTitlesButton.className = "copy-titles";
    copyTitlesButton.textContent = "Copy titles";
    copyTitlesButton.disabled = true;

    const status = document.createElement("div");
    status.className = "status";
    status.setAttribute("aria-live", "polite");

    section.append(count, historyCount, selectVisibleButton, clearButton, copyButton, copyTitlesButton, status);
    shadow.append(section);
    document.documentElement.append(host);

    selectVisibleButton.addEventListener("click", () => {
      for (const checkbox of document.querySelectorAll("input." + CHECKBOX_CLASS)) {
        const id = checkbox.dataset.videoId;
        const url = checkbox.dataset.videoUrl;
        const title = checkbox.dataset.videoTitle;
        if (id && url) selectedVideos.set(id, { url, title: title || "Untitled video" });
      }
      syncCheckboxes();
      status.textContent = "Visible videos selected.";
    });

    clearButton.addEventListener("click", () => {
      selectedVideos.clear();
      syncCheckboxes();
      status.textContent = "Selection cleared.";
    });

    copyButton.addEventListener("click", () => void copySelected("url"));
    copyTitlesButton.addEventListener("click", () => void copySelected("title"));

    panel = { host, count, historyCount, status, copyButton, copyTitlesButton, clearButton };
    updatePanel();
  }

  async function copySelected(field) {
    await historyLoadPromise;
    const selection = Array.from(selectedVideos.entries());
    const values = selection.map(([, video]) => video)
      .map((video) => video[field])
      .filter((value) => typeof value === "string" && value.trim());
    if (!values.length) return;
    const text = values.join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      if (!copyWithFallback(text)) {
        panel.status.textContent = "Could not access the clipboard. Check the extension permission.";
        return;
      }
    }
    const copiedLabel = "Copied " + values.length + (field === "title" ? " title" : " link") + (values.length === 1 ? "" : "s");
    if (field === "url") {
      let historySaved = true;
      try {
        await rememberSelectedVideos(selection);
      } catch {
        historySaved = false;
      }
      panel.status.textContent = historySaved
        ? copiedLabel + " and marked " + selection.length + " as picked."
        : copiedLabel + ", but the picked labels could not be saved.";
      return;
    }
    panel.status.textContent = copiedLabel + ".";
  }

  function readPickedHistory() {
    return new Promise((resolve, reject) => {
      chrome.storage.local.get(null, (result) => {
        const error = chrome.runtime.lastError;
        if (error) {
          reject(new Error(error.message));
          return;
        }
        const history = new Map(Object.entries(result[PICKED_STORAGE_KEY] || {}));
        for (const [key, item] of Object.entries(result)) {
          if (!key.startsWith(PICKED_VIDEO_STORAGE_PREFIX)) continue;
          const id = key.slice(PICKED_VIDEO_STORAGE_PREFIX.length);
          const previous = history.get(id);
          if (!previous || pickedTimestamp(item) >= pickedTimestamp(previous)) history.set(id, item);
        }
        resolve(Object.fromEntries(history));
      });
    });
  }

  function writePickedHistory(history) {
    const updates = Object.fromEntries(Object.entries(history).map(([id, item]) => [
      PICKED_VIDEO_STORAGE_PREFIX + id,
      item
    ]));
    return new Promise((resolve, reject) => {
      chrome.storage.local.set(updates, () => {
        const error = chrome.runtime.lastError;
        if (error) {
          reject(new Error(error.message));
          return;
        }
        resolve();
      });
    });
  }

  function pickedTimestamp(item) {
    const timestamp = Date.parse(item && item.lastPickedAt);
    return Number.isFinite(timestamp) ? timestamp : 0;
  }

  function mergePickedVideo(id, item) {
    if (!/^[A-Za-z0-9_-]{11}$/.test(id) || !item || typeof item.lastPickedAt !== "string") return false;
    const previous = pickedVideos.get(id);
    if (previous && pickedTimestamp(item) < pickedTimestamp(previous)) return false;
    pickedVideos.set(id, item);
    return true;
  }

  async function loadPickedHistory() {
    try {
      const history = await readPickedHistory();
      for (const [id, item] of Object.entries(history)) mergePickedVideo(id, item);
      historyLoadSucceeded = true;
      syncCheckboxes();
      updatePanel();
    } catch {
      historyLoadSucceeded = false;
      if (panel) panel.status.textContent = "Could not load picked-video history.";
    }
  }

  async function rememberSelectedVideos(selection) {
    if (!historyLoadSucceeded) throw new Error("Picked-video history is unavailable.");
    const storedHistory = await readPickedHistory();
    const now = new Date().toISOString();
    const nextHistory = new Map(pickedVideos);
    for (const [id, item] of Object.entries(storedHistory)) {
      const previous = nextHistory.get(id);
      if (!previous || pickedTimestamp(item) >= pickedTimestamp(previous)) nextHistory.set(id, item);
    }
    const updates = new Map();
    for (const [id, video] of selection) {
      const previous = nextHistory.get(id);
      const item = {
        id,
        url: video.url,
        title: video.title || "Untitled video",
        firstPickedAt: previous ? previous.firstPickedAt : now,
        lastPickedAt: now
      };
      nextHistory.set(id, item);
      updates.set(id, item);
    }
    await writePickedHistory(Object.fromEntries(updates));
    for (const [id, item] of nextHistory) mergePickedVideo(id, item);
    syncCheckboxes();
    updatePanel();
  }

  function pickedDateLabel(item) {
    const date = new Date(item.lastPickedAt);
    if (Number.isNaN(date.getTime())) return "Đã chọn";
    return "Đã chọn " + new Intl.DateTimeFormat("vi-VN", {
      day: "2-digit",
      month: "2-digit"
    }).format(date);
  }

  function updatePickedBadge(thumbnail, videoId) {
    let badge = Array.from(thumbnail.children).find((child) =>
      child.classList && child.classList.contains(PICKED_BADGE_CLASS)
    );
    const picked = pickedVideos.get(videoId);
    if (!picked) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = document.createElement("span");
      badge.className = PICKED_BADGE_CLASS;
      thumbnail.append(badge);
    }
    const label = pickedDateLabel(picked);
    if (badge.textContent !== label) badge.textContent = label;
    if (badge.dataset.videoId !== videoId) badge.dataset.videoId = videoId;
    const fullDate = new Date(picked.lastPickedAt).toLocaleString("vi-VN");
    if (badge.title !== "Đã chọn " + fullDate) badge.title = "Đã chọn " + fullDate;
    if (badge.getAttribute("aria-label") !== "Video đã chọn " + fullDate) {
      badge.setAttribute("aria-label", "Video đã chọn " + fullDate);
    }
  }

  function copyWithFallback(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-10000px";
    textarea.style.top = "0";
    document.body.append(textarea);
    textarea.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } finally {
      textarea.remove();
    }
    return copied;
  }

  function updatePanel() {
    if (!panel) return;
    const count = selectedVideos.size;
    panel.count.textContent = count + " video" + (count === 1 ? "" : "s") + " selected";
    panel.historyCount.textContent = pickedVideos.size + " previously picked";
    panel.copyButton.disabled = count === 0;
    panel.copyTitlesButton.disabled = count === 0;
    panel.clearButton.disabled = count === 0;
  }

  function syncCheckboxes() {
    for (const checkbox of document.querySelectorAll("input." + CHECKBOX_CLASS)) {
      checkbox.checked = selectedVideos.has(checkbox.dataset.videoId);
      const overlay = checkbox.closest("." + OVERLAY_CLASS);
      if (overlay && overlay.parentElement) {
        updatePickedBadge(overlay.parentElement, checkbox.dataset.videoId);
      }
    }
    updatePanel();
  }

  function addCheckbox(anchor, card, video) {
    const thumbnailAnchor = card.querySelector("a#thumbnail[href]") || anchor;
    const thumbnail = thumbnailAnchor.parentElement || card;
    thumbnail.classList.add(THUMBNAIL_CLASS);
    let overlay = Array.from(thumbnail.children).find((child) => child.classList && child.classList.contains(OVERLAY_CLASS));
    if (!overlay) {
      overlay = document.createElement("label");
      overlay.className = OVERLAY_CLASS;
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = CHECKBOX_CLASS;
      checkbox.addEventListener("click", (event) => event.stopPropagation());
      checkbox.addEventListener("change", () => {
        const id = checkbox.dataset.videoId;
        const url = checkbox.dataset.videoUrl;
        const title = checkbox.dataset.videoTitle;
        if (!id || !url) return;
        if (checkbox.checked) {
          selectedVideos.set(id, { url, title: title || "Untitled video" });
        } else {
          selectedVideos.delete(id);
        }
        syncCheckboxes();
      });
      overlay.append(checkbox);
      thumbnail.append(overlay);
    }
    const checkbox = overlay.querySelector("input." + CHECKBOX_CLASS);
    checkbox.dataset.videoId = video.id;
    checkbox.dataset.videoUrl = video.url;
    checkbox.dataset.videoTitle = video.title || "Untitled video";
    checkbox.setAttribute("aria-label", "Select video " + video.id);
    checkbox.checked = selectedVideos.has(video.id);
  }

  function scanPage() {
    if (!document.body) return;
    if (!panel) createPanel();
    panel.host.style.display = isChannelPage() ? "block" : "none";
    if (!isChannelPage()) return;

    const visitedCards = new Set();
    for (const anchor of document.querySelectorAll(LINK_SELECTOR)) {
      const card = anchor.closest(CARD_SELECTOR);
      if (!card || visitedCards.has(card)) continue;
      const video = videoFromLink(anchor);
      if (!video) continue;
      video.title = videoTitleFromCard(card, anchor);
      visitedCards.add(card);
      addCheckbox(anchor, card, video);
    }
    syncCheckboxes();
  }

  function scheduleScan() {
    window.clearTimeout(scanTimer);
    scanTimer = window.setTimeout(scanPage, 120);
  }

  const observer = new MutationObserver(scheduleScan);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("yt-navigate-finish", scheduleScan);
  window.addEventListener("yt-page-data-updated", scheduleScan);
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local") return;
    let historyChanged = false;
    const legacyHistory = changes[PICKED_STORAGE_KEY] && changes[PICKED_STORAGE_KEY].newValue;
    if (legacyHistory && typeof legacyHistory === "object") {
      for (const [id, item] of Object.entries(legacyHistory)) {
        historyChanged = mergePickedVideo(id, item) || historyChanged;
      }
    }
    for (const [key, change] of Object.entries(changes)) {
      if (!key.startsWith(PICKED_VIDEO_STORAGE_PREFIX)) continue;
      const id = key.slice(PICKED_VIDEO_STORAGE_PREFIX.length);
      historyChanged = mergePickedVideo(id, change.newValue) || historyChanged;
    }
    if (historyChanged) syncCheckboxes();
  });
  historyLoadPromise = loadPickedHistory();
  scheduleScan();
})();
