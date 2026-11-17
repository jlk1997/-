(() => {
  const ORIGIN = window.location.origin;

  function trustedPairPage() {
    const { hostname, port, href } = window.location;
    if ((hostname === "127.0.0.1" || hostname === "localhost") && (port === "10086" || port === "80" || !port)) {
      return true;
    }
    if (/packageCreator|pages\/accounts|creator\/accounts|creator\/hub/i.test(href)) return true;
    if (document.documentElement && document.documentElement.getAttribute("data-bittune-connector")) return true;
    return Boolean(document.querySelector("[data-bittune-connector], meta[name='bittune-app']"));
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== ORIGIN) return;
    if (!trustedPairPage()) return;
    const data = event.data || {};
    if (data.type === "BITTUNE_PAIR_PROBE" || data.type === "BITTUNE_STATUS_PROBE") {
      chrome.runtime.sendMessage({ type: "ui-state" }, (res) => {
        window.postMessage(
          {
            type: data.type === "BITTUNE_STATUS_PROBE" ? "BITTUNE_STATUS" : "BITTUNE_PAIR_PONG",
            installed: true,
            version: res && res.extensionVersion,
            period: res && res.period,
            lastHarvest: res && res.lastHarvest,
            online: Boolean(res && res.token && res.syncOk !== false),
            lastSyncAt: res && res.lastSyncAt,
          },
          ORIGIN,
        );
      });
      return;
    }
    if (data.type === "BITTUNE_PAIR") {
      const pair = data.pair || {};
      if (!pair.token || !pair.apiBase) {
        window.postMessage({ type: "BITTUNE_PAIR_OK", ok: false, error: "incomplete_pair" }, ORIGIN);
        return;
      }
      chrome.runtime.sendMessage(
        {
          type: "pair-settings",
          apiBase: pair.apiBase,
          token: pair.token,
          channel: pair.channel,
          role: pair.role,
          period: pair.period,
          expires_at: pair.expires_at,
          minVersion: pair.minVersion,
          user_id: pair.user_id,
          webBase: pair.webBase,
        },
        (res) => {
          window.postMessage({ type: "BITTUNE_PAIR_OK", ok: Boolean(res && res.ok), error: res && res.error }, ORIGIN);
        },
      );
      return;
    }
    if (data.type === "BITTUNE_UNPAIR") {
      chrome.runtime.sendMessage({ type: "unpair" }, (res) => {
        window.postMessage({ type: "BITTUNE_UNPAIR_OK", ok: Boolean(res && res.ok), error: res && res.error }, ORIGIN);
      });
      return;
    }
    if (data.type === "BITTUNE_COMMAND") {
      chrome.runtime.sendMessage(
        { type: "seat-command", kind: data.kind, channel: data.channel, seatId: data.seatId, payload: data.payload },
        (res) => {
          window.postMessage({ type: "BITTUNE_COMMAND_OK", ok: Boolean(res && res.ok), error: res && res.error, kind: data.kind }, ORIGIN);
        },
      );
      return;
    }
    if (data.type === "BITTUNE_POLL") {
      chrome.runtime.sendMessage({ type: "seat-poll" }, (res) => {
        window.postMessage(
          { type: "BITTUNE_POLL_OK", ok: Boolean(res && res.ok), ran: res && res.ran, error: res && res.error },
          ORIGIN,
        );
      });
    }
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (!message || message.type !== "BITTUNE_APP_EVENT") return;
    window.postMessage(
      {
        type: message.event || "BITTUNE_SYNC", // BITTUNE_DELIVERY forwarded from worker
        lastHarvest: message.lastHarvest,
        sync: message.sync,
        deliveryId: message.deliveryId,
        channel: message.channel,
        event: message.event,
      },
      ORIGIN,
    );
  });
})();
