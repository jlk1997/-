(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.VibeHarvest = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const EXTRACTOR_VERSION = "2026.08.4";

  function parseNumber(raw) {
    if (raw == null) return 0;
    const n = Number(String(raw).replace(/,/g, "").replace(/[^\d.-]/g, ""));
    return Number.isFinite(n) ? n : 0;
  }

  function revenueMinor(raw) {
    const n = parseNumber(raw);
    if (!n) return 0;
    return Math.abs(n) >= 100 && Number.isInteger(n) ? Math.round(n) : Math.round(n * 100);
  }

  function headerIndex(cells, patterns) {
    return cells.findIndex((cell) => patterns.some((re) => re.test(cell)));
  }

  function detectCsvSep(headerLine) {
    const tabs = (headerLine.match(/\t/g) || []).length;
    const semis = (headerLine.match(/;/g) || []).length;
    const commas = (headerLine.match(/,/g) || []).length;
    if (tabs && tabs >= semis && tabs >= commas) return "\t";
    if (semis && semis > commas) return ";";
    return ",";
  }

  function splitCsvLine(line, sep) {
    const out = [];
    let cur = "";
    let inQuotes = false;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (ch === '"') {
        if (inQuotes && line[i + 1] === '"') {
          cur += '"';
          i += 1;
        } else {
          inQuotes = !inQuotes;
        }
      } else if (!inQuotes && ch === sep) {
        out.push(cur);
        cur = "";
      } else {
        cur += ch;
      }
    }
    out.push(cur);
    return out.map((cell) => cell.trim());
  }

  function extractTrackCode(text) {
    const match = String(text || "")
      .toUpperCase()
      .match(/\[?(VS[0-9A-F]{12})\]?/);
    return match ? match[1] : "";
  }

  function stampRow(row, channelCode) {
    const confidence =
      row.track_code && row.streams && row.revenue_minor
        ? 0.9
        : row.track_code || (row.streams && row.revenue_minor)
          ? 0.8
          : 0.7;
    return {
      ...row,
      channel_code: row.channel_code || channelCode,
      confidence: row.confidence != null ? row.confidence : confidence,
      extractor_version: EXTRACTOR_VERSION,
    };
  }

  function harvestVisibleTables(doc, channelCode) {
    const streamPat = [/播放/, /streams?/i, /plays?/i, /quantity/i, /收听/, /次数/];
    const titlePat = [/title/i, /曲名/, /歌曲/, /track/i, /song/i, /名称/];
    const revenuePat = [/收益/, /收入/, /revenue/i, /earnings?/i, /净额/, /金额/];
    const isrcPat = [/isrc/i, /曲目码/];
    const rows = [];
    (doc || document).querySelectorAll("table").forEach((table) => {
      const headerCells = Array.from(table.querySelectorAll("thead th, tr:first-child th, tr:first-child td")).map((el) =>
        (el.textContent || "").trim(),
      );
      if (!headerCells.length) return;
      const streamIdx = headerIndex(headerCells, streamPat);
      const titleIdx = headerIndex(headerCells, titlePat);
      const revenueIdx = headerIndex(headerCells, revenuePat);
      const isrcIdx = headerIndex(headerCells, isrcPat);
      if (streamIdx < 0 && revenueIdx < 0) return;
      Array.from(table.querySelectorAll("tr"))
        .slice(1)
        .forEach((tr) => {
          const cells = Array.from(tr.querySelectorAll("td")).map((td) => (td.textContent || "").trim());
          if (!cells.length) return;
          const title = (titleIdx >= 0 ? cells[titleIdx] : cells[0]) || "";
          const streams = streamIdx >= 0 ? parseNumber(cells[streamIdx]) : 0;
          const revenue = revenueIdx >= 0 ? revenueMinor(cells[revenueIdx]) : 0;
          if (!title && !streams && !revenue) return;
          const code = extractTrackCode(title);
          const isrc = (isrcIdx >= 0 ? cells[isrcIdx] : "") || code || undefined;
          rows.push(
            stampRow(
              {
                title,
                channel_code: channelCode,
                isrc,
                track_code: code || undefined,
                streams,
                revenue_minor: revenue,
                currency: /usd|\$/i.test(headerCells.join(" ") + " " + cells.join(" ")) ? "USD" : "CNY",
              },
              channelCode,
            ),
          );
        });
    });
    return rows;
  }

  function harvestMarkedCards(doc, channelCode, hints) {
    const selector = (hints && hints.cardSelector) || "[data-vibe-row]";
    const nodes = (doc || document).querySelectorAll(selector);
    const rows = [];
    Array.from(nodes || []).forEach((el) => {
      const title =
        (el.getAttribute && (el.getAttribute("data-title") || el.getAttribute("data-track"))) ||
        ((el.querySelector && el.querySelector("[data-title], .title, .song-name, .song_name")) || {}).textContent ||
        "";
      const streamsRaw =
        (el.getAttribute && (el.getAttribute("data-streams") || el.getAttribute("data-plays") || el.getAttribute("data-views"))) ||
        ((el.querySelector && el.querySelector("[data-streams], .streams, .play-count")) || {}).textContent ||
        "";
      const revenueRaw =
        (el.getAttribute && (el.getAttribute("data-revenue") || el.getAttribute("data-earnings"))) ||
        ((el.querySelector && el.querySelector("[data-revenue], .revenue, .earnings")) || {}).textContent ||
        "";
      const streams = parseNumber(streamsRaw);
      const revenue = revenueMinor(revenueRaw);
      if (!title && !streams && !revenue) return;
      const code = extractTrackCode(title);
      rows.push(
        stampRow(
          {
            title: String(title).trim(),
            channel_code: channelCode,
            track_code: code || undefined,
            streams,
            revenue_minor: revenue,
            currency: hints && hints.currency ? hints.currency : /usd|\$/i.test(String(revenueRaw)) ? "USD" : "CNY",
            raw: { source: "card" },
          },
          channelCode,
        ),
      );
    });
    return rows;
  }

  function harvestWithHints(doc, channelCode, hints) {
    const cards = harvestMarkedCards(doc, channelCode, hints || {});
    const tables = harvestVisibleTables(doc, channelCode);
    const seen = new Set();
    const merged = [];
    cards.concat(tables).forEach((row) => {
      const key = `${row.track_code || ""}|${row.title}|${row.streams}|${row.revenue_minor}`;
      if (seen.has(key)) return;
      seen.add(key);
      if (hints && hints.currency && !row.currency) row.currency = hints.currency;
      merged.push(row);
    });
    return merged;
  }

  const CHANNEL_EXTRACTORS = {
    netease: (doc, code) => harvestWithHints(doc, code, { currency: "CNY", cardSelector: ".song-item, [data-vibe-row]" }),
    qq_music: (doc, code) => harvestWithHints(doc, code, { currency: "CNY", cardSelector: ".song_item, [data-vibe-row]" }),
    kugou: (doc, code) => harvestWithHints(doc, code, { currency: "CNY", cardSelector: "[data-vibe-row]" }),
    kuwo: (doc, code) => harvestWithHints(doc, code, { currency: "CNY", cardSelector: "[data-vibe-row]" }),
    qishui: (doc, code) => harvestWithHints(doc, code, { currency: "CNY", cardSelector: ".track-card, [data-vibe-row]" }),
    spotify: (doc, code) => harvestWithHints(doc, code, { currency: "USD", cardSelector: "[data-testid='row'], [data-vibe-row]" }),
    apple_music: (doc, code) => harvestWithHints(doc, code, { currency: "USD", cardSelector: ".song-row, [data-vibe-row]" }),
    youtube_music: (doc, code) => harvestWithHints(doc, code, { currency: "USD", cardSelector: "[data-views], [data-vibe-row]" }),
    douyin_musician: (doc, code) => harvestWithHints(doc, code, { currency: "CNY", cardSelector: "[data-vibe-row]" }),
    bilibili: (doc, code) => harvestWithHints(doc, code, { currency: "CNY" }),
    wechat_channels: (doc, code) => harvestWithHints(doc, code, { currency: "CNY" }),
    kuaishou_musician: (doc, code) => harvestWithHints(doc, code, { currency: "CNY" }),
    tiktok_music: (doc, code) => harvestWithHints(doc, code, { currency: "USD" }),
    amazon_music: (doc, code) => harvestWithHints(doc, code, { currency: "USD" }),
    deezer: (doc, code) => harvestWithHints(doc, code, { currency: "EUR" }),
    soundcloud: (doc, code) => harvestWithHints(doc, code, { currency: "USD" }),
    bandcamp: (doc, code) => harvestWithHints(doc, code, { currency: "USD" }),
  };

  function harvestChannel(doc, channelCode) {
    const fn = CHANNEL_EXTRACTORS[channelCode] || harvestVisibleTables;
    return fn(doc, channelCode).map((row) => stampRow(row, channelCode));
  }

  function parseOfficialCsv(text, channelCode) {
    const lines = String(text || "")
      .replace(/^\uFEFF/, "")
      .split(/\r?\n/)
      .filter((line) => line.trim());
    if (lines.length < 2) return [];
    const sep = detectCsvSep(lines[0]);
    const headers = splitCsvLine(lines[0], sep).map((cell) => cell.replace(/^"|"$/g, ""));
    const streamIdx = headerIndex(headers, [/播放/, /streams?/i, /plays?/i, /quantity/i, /收听/, /次数/]);
    const titleIdx = headerIndex(headers, [/title/i, /曲名/, /歌曲/, /track/i, /song/i, /名称/]);
    const revenueIdx = headerIndex(headers, [/收益/, /收入/, /revenue/i, /earnings?/i, /净额/, /金额/]);
    const isrcIdx = headerIndex(headers, [/isrc/i, /曲目码/]);
    if (streamIdx < 0 && revenueIdx < 0) return [];
    return lines.slice(1).flatMap((line) => {
      const cells = splitCsvLine(line, sep).map((cell) => cell.replace(/^"|"$/g, ""));
      const title = (titleIdx >= 0 ? cells[titleIdx] : cells[0]) || "";
      const streams = streamIdx >= 0 ? parseNumber(cells[streamIdx]) : 0;
      const revenue = revenueIdx >= 0 ? revenueMinor(cells[revenueIdx]) : 0;
      if (!title && !streams && !revenue) return [];
      const code = extractTrackCode(title);
      return [
        stampRow(
          {
            title,
            channel_code: channelCode,
            isrc: (isrcIdx >= 0 ? cells[isrcIdx] : "") || code || undefined,
            track_code: code || undefined,
            streams,
            revenue_minor: revenue,
            currency: /usd|\$/i.test(headers.join(" ") + " " + cells.join(" ")) ? "USD" : /eur|€/i.test(headers.join(" ") + " " + cells.join(" ")) ? "EUR" : "CNY",
            confidence: 0.95,
          },
          channelCode,
        ),
      ];
    });
  }

  return {
    EXTRACTOR_VERSION,
    harvestVisibleTables,
    harvestMarkedCards,
    harvestChannel,
    parseOfficialCsv,
    parseNumber,
    revenueMinor,
    extractTrackCode,
  };
});
