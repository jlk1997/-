(() => {
  if (window.__bittuneOverlay) return;
  window.__bittuneOverlay = true;
  document.documentElement.dataset.bittuneOverlay = "1";

  const copy = () => (self.VibeUi && self.VibeUi.overlayCopy && self.VibeUi.overlayCopy()) || {};

  let state = {
    show: false,
    channel: "",
    name: "",
    paired: false,
    hasLicense: false,
    scopes: { metrics: true, export_csv: true, settle: false, upload: true, keep_sync: false },
    fields: { streams: true, tracks: true, geo: true, audience: false },
    busy: false,
    title: "",
    hint: "",
    last: "",
    error: "",
    showFields: false,
  };

  function el(tag, style, text) {
    const node = document.createElement(tag);
    if (style) node.style.cssText = style;
    if (text) node.textContent = text;
    return node;
  }

  function hasUsefulFields() {
    return Boolean(state.fields.streams || state.fields.tracks);
  }

  function requestSync(settle) {
    const t = copy();
    if (!hasUsefulFields()) {
      state.error = t.needField || "";
      paint();
      return;
    }
    if (state.busy) return;
    state.busy = true;
    state.error = "";
    paint();
    chrome.runtime.sendMessage(
      {
        type: "overlay-sync",
        settle: Boolean(settle),
        fields: state.fields,
        channel: state.channel,
      },
      (res) => {
        const runtimeErr = chrome.runtime.lastError;
        state.busy = false;
        if (res && res.ok && !runtimeErr) {
          state.error = "";
          state.last = (t.last || "上次同步 {n} 行").replace("{n}", String(res.rows || 0));
        } else {
          state.error = (res && res.error) || (runtimeErr && runtimeErr.message) || t.syncFail || "";
        }
        paint();
      },
    );
  }

  function paint() {
    const old = document.querySelector("[data-bittune-overlay]");
    if (old) old.remove();
    if (!state.show || sessionStorage.getItem("bittune-overlay-hide") === location.hostname) return;
    const t = copy();

    const box = el(
      "div",
      "position:fixed;right:16px;bottom:16px;z-index:2147483646;width:min(360px,calc(100vw - 24px));padding:14px 14px 12px;border-radius:16px;background:#1b1b1b;color:#f7f4ee;font:13px/1.45 Segoe UI,PingFang SC,sans-serif;box-shadow:0 12px 32px rgba(0,0,0,.32);",
    );
    box.setAttribute("data-bittune-overlay", "1");

    const head = el("div", "display:flex;justify-content:space-between;gap:8px;align-items:flex-start;");
    const title = el("div", "");
    title.appendChild(el("b", "display:block;margin-bottom:2px", state.name || t.brand || "比特音连接器"));
    const hintText = state.busy
      ? t.syncing || "同步中…"
      : state.paired
        ? t.loggedIn || ""
        : t.needPair || "";
    title.appendChild(el("span", "opacity:.82", hintText));
    const close = el("button", "border:0;background:transparent;color:#fff;font-size:18px;cursor:pointer;line-height:1;", "×");
    close.onclick = () => {
      sessionStorage.setItem("bittune-overlay-hide", location.hostname);
      box.remove();
    };
    head.appendChild(title);
    head.appendChild(close);
    box.appendChild(head);

    if (state.paired && state.channel) {
      const range = el(
        "button",
        "margin:10px 0 6px;border:0;background:transparent;color:#c9b8f0;padding:0;cursor:pointer;font:12px/1.4 inherit;",
        state.showFields ? t.hideFields || "收起范围" : t.changeFields || "改范围",
      );
      range.onclick = () => {
        state.showFields = !state.showFields;
        paint();
      };
      box.appendChild(range);

      if (state.showFields) {
        const fields = [
          { id: "streams", label: t.streams || "播放" },
          { id: "tracks", label: t.tracks || "歌曲" },
          { id: "geo", label: t.geo || "地区" },
          { id: "audience", label: t.audience || "听众" },
        ];
        const list = el("div", "margin:0 0 8px;display:grid;gap:6px;");
        fields.forEach((field) => {
          const row = el("label", "display:flex;gap:8px;align-items:center;opacity:.95;cursor:pointer;");
          const boxInput = document.createElement("input");
          boxInput.type = "checkbox";
          boxInput.checked = Boolean(state.fields[field.id]);
          boxInput.onchange = () => {
            state.fields[field.id] = boxInput.checked;
          };
          row.appendChild(boxInput);
          row.appendChild(document.createTextNode(field.label));
          list.appendChild(row);
        });
        box.appendChild(list);
      }

      const settleRow = el("label", "display:flex;gap:8px;align-items:center;margin:4px 0 10px;cursor:pointer;");
      const settle = document.createElement("input");
      settle.type = "checkbox";
      settle.checked = Boolean(state.scopes.settle) && Boolean(state.hasLicense);
      settle.disabled = !state.hasLicense;
      settleRow.appendChild(settle);
      settleRow.appendChild(document.createTextNode(t.settleBox || "记进钱包"));
      box.appendChild(settleRow);
      if (!state.hasLicense) {
        box.appendChild(el("div", "opacity:.75;font-size:12px;margin:-4px 0 10px;", t.needLicense || ""));
      }

      const actions = el("div", "display:flex;gap:8px;flex-wrap:wrap;align-items:center;");
      const primary = el(
        "button",
        "border:0;border-radius:10px;padding:9px 12px;background:#c9b8f0;color:#1b1b1b;cursor:pointer;font-weight:600;flex:1;",
        state.busy ? t.syncing || "同步中…" : t.sync || "同步到比特音",
      );
      primary.disabled = state.busy;
      primary.onclick = () => requestSync(false);
      const settleBtn = el(
        "button",
        "border:0;border-radius:10px;padding:9px 12px;background:#e8c9a8;color:#1b1b1b;cursor:pointer;font-weight:600;flex:1;",
        t.syncSettle || "同步并入账",
      );
      settleBtn.style.display = state.hasLicense && settle.checked ? "" : "none";
      settle.onchange = () => {
        state.scopes.settle = settle.checked;
        settleBtn.style.display = state.hasLicense && settle.checked ? "" : "none";
      };
      settleBtn.onclick = () => requestSync(true);
      const desk = el(
        "button",
        "border:0;background:transparent;color:#c9b8f0;padding:8px 4px;cursor:pointer;",
        t.openHub || "去看账",
      );
      desk.onclick = () => chrome.runtime.sendMessage({ type: "open-app" });
      actions.appendChild(primary);
      actions.appendChild(settleBtn);
      actions.appendChild(desk);
      box.appendChild(actions);
    } else {
      const go = el(
        "button",
        "margin-top:10px;width:100%;border:0;border-radius:10px;padding:9px 12px;background:#c9b8f0;color:#1b1b1b;cursor:pointer;font-weight:600;",
        state.actionLabel || t.openConnector || "打开连接器",
      );
      go.onclick = () => chrome.runtime.sendMessage({ type: state.action || "open-popup" });
      box.appendChild(go);
    }

    if (state.error) {
      box.appendChild(el("div", "margin-top:8px;color:#f0b8b4;font-size:12px;", state.error));
    } else if (state.last) {
      box.appendChild(el("div", "margin-top:8px;opacity:.75;font-size:12px;", state.last));
    }

    document.documentElement.appendChild(box);
  }

  function refresh() {
    chrome.runtime.sendMessage({ type: "overlay-state", url: location.href }, (res) => {
      if (!res) return;
      state = { ...state, ...res, fields: { ...state.fields, ...(res.fields || {}) }, showFields: state.showFields };
      if (res.error) state.error = res.error;
      else if (res.last) state.error = "";
      paint();
    });
  }

  document.addEventListener("bittune-page-event", (event) => {
    const detail = (event && event.detail) || {};
    chrome.runtime.sendMessage({ type: "page-event", ...detail, url: location.href });
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (!message) return;
    if (message.type === "overlay-refresh" || message.type === "coach-refresh") refresh();
  });
  refresh();
})();
