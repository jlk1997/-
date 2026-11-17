/* Visible-session extractors only. No passwords, no hidden APIs. */
(() => {
  function hostChannel() {
    if (typeof VibeRunner !== "undefined" && VibeRunner.detectChannel) {
      return VibeRunner.detectChannel(location.href) || undefined;
    }
    const host = location.hostname || "";
    const CHANNEL_HOSTS = [
      [/music\.163\.com/i, "netease"],
      [/y\.qq\.com/i, "qq_music"],
      [/kugou\.com/i, "kugou"],
      [/kuwo\.cn/i, "kuwo"],
      [/music\.douyin\.com/i, "qishui"],
      [/bilibili\.com/i, "bilibili"],
      [/artists\.spotify\.com/i, "spotify"],
      [/artists\.apple\.com/i, "apple_music"],
      [/studio\.youtube\.com/i, "youtube_music"],
    ];
    const hit = CHANNEL_HOSTS.find(([re]) => re.test(host));
    return hit ? hit[1] : undefined;
  }

  function parseNumber(raw) {
    if (raw == null) return 0;
    const text = String(raw).replace(/,/g, "").replace(/[^\d.-]/g, "");
    const n = Number(text);
    return Number.isFinite(n) ? n : 0;
  }

  function revenueMinor(raw) {
    const n = parseNumber(raw);
    if (!n) return 0;
    return Math.abs(n) >= 100 && Number.isInteger(n) ? Math.round(n) : Math.round(n * 100);
  }

  function fromFixture() {
    const area = document.querySelector("[data-vibe-connector]");
    if (area && "value" in area && area.value) {
      try {
        const parsed = JSON.parse(area.value);
        return Array.isArray(parsed) ? parsed : parsed.rows || [];
      } catch {
        return [];
      }
    }
    if (Array.isArray(window.__VIBE_CONNECTOR_ROWS__)) return window.__VIBE_CONNECTOR_ROWS__;
    return [];
  }

  function fromMarkedNodes() {
    return Array.from(document.querySelectorAll("[data-vibe-metric]")).map((node) => ({
      title: node.getAttribute("data-vibe-title") || node.textContent.trim(),
      channel_code: node.getAttribute("data-vibe-channel") || hostChannel(),
      external_track_id: node.getAttribute("data-vibe-external-id") || undefined,
      isrc: node.getAttribute("data-vibe-isrc") || undefined,
      streams: Number(node.getAttribute("data-vibe-streams") || 0),
      revenue_minor: Number(node.getAttribute("data-vibe-revenue-minor") || 0),
      currency: node.getAttribute("data-vibe-currency") || "CNY",
      confidence: 0.4,
      raw: { source: "marked_node" },
    }));
  }

  function headerIndex(cells, patterns) {
    return cells.findIndex((cell) => patterns.some((re) => re.test(cell)));
  }

  function fromVisibleTables() {
    const streamPat = [/播放/, /streams?/i, /plays?/i, /quantity/i, /收听/, /次数/];
    const titlePat = [/title/i, /曲名/, /歌曲/, /track/i, /song/i, /名称/];
    const revenuePat = [/收益/, /收入/, /revenue/i, /earnings?/i, /净额/, /金额/];
    const isrcPat = [/isrc/i];
    const rows = [];
    document.querySelectorAll("table").forEach((table) => {
      const headerCells = Array.from(table.querySelectorAll("thead th, tr:first-child th, tr:first-child td")).map((el) =>
        (el.textContent || "").trim(),
      );
      if (!headerCells.length) return;
      const streamIdx = headerIndex(headerCells, streamPat);
      const titleIdx = headerIndex(headerCells, titlePat);
      const revenueIdx = headerIndex(headerCells, revenuePat);
      const isrcIdx = headerIndex(headerCells, isrcPat);
      if (streamIdx < 0 && revenueIdx < 0) return;
      Array.from(table.querySelectorAll("tr")).slice(1).forEach((tr) => {
        const cells = Array.from(tr.querySelectorAll("td")).map((td) => (td.textContent || "").trim());
        if (!cells.length) return;
        const title = (titleIdx >= 0 ? cells[titleIdx] : cells[0]) || "";
        const streams = streamIdx >= 0 ? parseNumber(cells[streamIdx]) : 0;
        const revenue = revenueIdx >= 0 ? revenueMinor(cells[revenueIdx]) : 0;
        if (!title && !streams && !revenue) return;
        const code =
          (typeof VibeHarvest !== "undefined" && VibeHarvest.extractTrackCode
            ? VibeHarvest.extractTrackCode(title)
            : (String(title || "").toUpperCase().match(/\[?(VS[0-9A-F]{12})\]?/) || [])[1]) || "";
        rows.push({
          title,
          channel_code: hostChannel(),
          isrc: (isrcIdx >= 0 ? cells[isrcIdx] : "") || code || undefined,
          track_code: code || undefined,
          streams,
          revenue_minor: revenue,
          currency: /usd|\$/i.test(headerCells.join(" ")) ? "USD" : "CNY",
          confidence: 0.35,
          raw: { source: "visible_table", host: location.hostname },
        });
      });
    });
    return rows;
  }

  function fromOfficialCsv() {
    if (typeof VibeHarvest === "undefined" || !VibeHarvest.parseOfficialCsv) return [];
    const channel = hostChannel();
    const blobs = [];
    document.querySelectorAll("textarea, pre, [data-vibe-csv]").forEach((el) => {
      const text = ("value" in el && el.value) || el.textContent || "";
      if (text.includes(",") && /title|曲名|track|streams|播放|revenue|收益/i.test(text.split("\n")[0] || "")) {
        blobs.push(text);
      }
    });
    return blobs.flatMap((text) => VibeHarvest.parseOfficialCsv(text, channel) || []);
  }

  const csvRows = fromOfficialCsv();
  const tableRows = csvRows.length
    ? []
    : typeof VibeHarvest !== "undefined" && (VibeHarvest.harvestChannel || VibeHarvest.harvestVisibleTables)
      ? (VibeHarvest.harvestChannel || VibeHarvest.harvestVisibleTables)(document, hostChannel())
      : fromVisibleTables();
  const rows = [...fromFixture(), ...csvRows, ...fromMarkedNodes(), ...tableRows].filter(
    (row) => row.title || row.external_track_id || row.streams || row.revenue_minor,
  );
  return rows;
})();
