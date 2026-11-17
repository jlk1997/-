export function markBittunePage() {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-bittune-connector", "1");
}

export type ConnectorPair = {
  vibePair?: number;
  apiBase: string;
  token: string;
  role?: string;
  channel?: string;
  period?: string;
  expires_at?: string;
  minVersion?: string;
  user_id?: string;
  webBase?: string;
};

export type ExtensionStatus = {
  installed: boolean;
  version?: string;
  period?: string;
  online?: boolean;
  lastSyncAt?: string;
  lastHarvest?: {
    channel?: string;
    count?: number;
    matched?: number;
    at?: string;
  };
};

export function pairFromMinted(minted: {
  pair?: ConnectorPair;
  pair_text?: string;
  token: string;
  api_base?: string;
  role?: string;
  period_key?: string;
  expires_at?: string;
  min_extension_version?: string;
}): ConnectorPair {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  if (minted.pair?.token && minted.pair.apiBase) {
    return { ...minted.pair, webBase: minted.pair.webBase || origin };
  }
  if (minted.pair_text?.startsWith("BITTUNE_PAIR:")) {
    try {
      const parsed = JSON.parse(minted.pair_text.slice("BITTUNE_PAIR:".length)) as ConnectorPair;
      return { ...parsed, webBase: parsed.webBase || origin };
    } catch {
      /* fall through */
    }
  }
  return {
    vibePair: 1,
    token: minted.token,
    apiBase: minted.api_base || "",
    role: minted.role,
    period: minted.period_key,
    expires_at: minted.expires_at,
    minVersion: minted.min_extension_version,
    webBase: origin,
  };
}

export function probeExtension(timeoutMs = 500): Promise<boolean> {
  return probeExtensionStatus(timeoutMs).then((status) => status.installed);
}

export function probeExtensionStatus(timeoutMs = 1500): Promise<ExtensionStatus> {
  if (typeof window === "undefined") return Promise.resolve({ installed: false });
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMsg);
      resolve({ installed: false });
    }, timeoutMs);
    const onMsg = (event: MessageEvent) => {
      if (event.source !== window) return;
      if (event.data?.type === "BITTUNE_PAIR_PONG" || event.data?.type === "BITTUNE_STATUS") {
        window.clearTimeout(timer);
        window.removeEventListener("message", onMsg);
        resolve({
          installed: true,
          version: event.data.version,
          period: event.data.period,
          online: event.data.online,
          lastSyncAt: event.data.lastSyncAt,
          lastHarvest: event.data.lastHarvest,
        });
      }
    };
    window.addEventListener("message", onMsg);
    window.postMessage({ type: "BITTUNE_STATUS_PROBE" }, window.location.origin);
    window.postMessage({ type: "BITTUNE_PAIR_PROBE" }, window.location.origin);
  });
}

export function sendPairToExtension(pair: ConnectorPair, timeoutMs = 2000): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMsg);
      resolve(false);
    }, timeoutMs);
    const onMsg = (event: MessageEvent) => {
      if (event.source !== window) return;
      if (event.data?.type === "BITTUNE_PAIR_OK") {
        window.clearTimeout(timer);
        window.removeEventListener("message", onMsg);
        resolve(Boolean(event.data.ok));
      }
    };
    window.addEventListener("message", onMsg);
    window.postMessage({ type: "BITTUNE_PAIR", pair }, window.location.origin);
  });
}

export function sendUnpairToExtension(timeoutMs = 800): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMsg);
      resolve(false);
    }, timeoutMs);
    const onMsg = (event: MessageEvent) => {
      if (event.source !== window) return;
      if (event.data?.type === "BITTUNE_UNPAIR_OK") {
        window.clearTimeout(timer);
        window.removeEventListener("message", onMsg);
        resolve(Boolean(event.data.ok));
      }
    };
    window.addEventListener("message", onMsg);
    window.postMessage({ type: "BITTUNE_UNPAIR" }, window.location.origin);
  });
}

export function sendCommandToExtension(
  command: { kind: string; seatId?: string; channel?: string; payload?: Record<string, unknown> },
  timeoutMs = 1500,
): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMsg);
      resolve(false);
    }, timeoutMs);
    const onMsg = (event: MessageEvent) => {
      if (event.source !== window) return;
      if (event.data?.type === "BITTUNE_COMMAND_OK") {
        window.clearTimeout(timer);
        window.removeEventListener("message", onMsg);
        resolve(Boolean(event.data.ok));
      }
    };
    window.addEventListener("message", onMsg);
    window.postMessage({ type: "BITTUNE_COMMAND", ...command }, window.location.origin);
  });
}

export function sendPollToExtension(timeoutMs = 4000): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMsg);
      resolve(false);
    }, timeoutMs);
    const onMsg = (event: MessageEvent) => {
      if (event.source !== window) return;
      if (event.data?.type === "BITTUNE_POLL_OK") {
        window.clearTimeout(timer);
        window.removeEventListener("message", onMsg);
        resolve(Boolean(event.data.ok));
      }
    };
    window.addEventListener("message", onMsg);
    window.postMessage({ type: "BITTUNE_POLL" }, window.location.origin);
  });
}

export function listenExtensionEvents(
  onEvent: (event: {
    type?: string;
    lastHarvest?: ExtensionStatus["lastHarvest"];
    deliveryId?: string;
    channel?: string;
    event?: string;
  }) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;
  const onMsg = (event: MessageEvent) => {
    if (event.source !== window) return;
    const type = event.data?.type;
    if (type === "BITTUNE_SYNC" || type === "BITTUNE_UNPAIRED" || type === "BITTUNE_DELIVERY") onEvent(event.data);
  };
  window.addEventListener("message", onMsg);
  return () => window.removeEventListener("message", onMsg);
}
