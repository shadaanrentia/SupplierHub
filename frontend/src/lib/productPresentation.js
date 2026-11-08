export const cleanColour = (value) =>
  String(value || "")
    .replace(/^[\s~]+/, "")
    .replace(/\s+/g, " ")
    .trim();
export function safeNumber(value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    typeof value === "boolean"
  )
    return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
export function money(value) {
  const n = safeNumber(value);
  return n === null
    ? "—"
    : new Intl.NumberFormat("en-CA", {
        style: "currency",
        currency: "CAD",
      }).format(n);
}
export function dateLabel(value) {
  if (!value) return "—";
  const text = String(value);
  const date = new Date(
    /(?:Z|[+-]\d{2}:?\d{2})$/.test(text) ? text : text + "Z",
  );
  return Number.isNaN(date.valueOf())
    ? "—"
    : date.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      });
}
export function jsonValue(value, fallback = []) {
  if (typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  }
  return value ?? fallback;
}
export function descriptionBlocks(value) {
  let text = String(value || "");
  if (typeof DOMParser !== "undefined") {
    text = text
      .replace(/<\s*br\s*\/?\s*>/gi, "\n")
      .replace(/<\/(?:p|div|li|h[1-6])\s*>/gi, "\n");
    text =
      new DOMParser().parseFromString(text, "text/html").body.textContent || "";
  } else {
    text = text.replace(/<\s*br\s*\/?\s*>/gi, "\n").replace(/<[^>]*>/g, "");
  }
  text = text
    .replace(/\r/g, "")
    .replace(/[\t ]+/g, " ")
    .trim();
  if (!text) return [];
  return text
    .split(
      /\n+|\s+-\s+|(?=(?:In Stock Colou?rs|Special Order Colou?rs|Special Order Conditions|NOTE)\s*:)/i,
    )
    .map((value) => value.trim())
    .filter(Boolean)
    .flatMap((block) => {
      if (block.length < 320) return [block];
      const sentences = block.split(/(?<=[.!?])\s+(?=[A-Z])/);
      const paragraphs = [];
      for (let i = 0; i < sentences.length; i += 3)
        paragraphs.push(sentences.slice(i, i + 3).join(" "));
      return paragraphs;
    });
}
export function groupImages(media, variants = []) {
  const groups = new Map(),
    seen = new Set();
  const byPart = new Map(
    variants.map((v) => [String(v.variant_sku || "").toLowerCase(), v.color]),
  );
  for (const item of media || []) {
    if (item.media_type && item.media_type !== "image") continue;
    const url = String(item.url || item.local_url || "").trim();
    if (!url || seen.has(url)) continue;
    seen.add(url);
    let colour = cleanColour(item.source_color || item.color);
    if (!colour) {
      const parts = jsonValue(item.source_part_ids, []);
      const colours = [
        ...new Set(
          (Array.isArray(parts) ? parts : [])
            .map((p) => byPart.get(String(p).toLowerCase()))
            .filter(Boolean),
        ),
      ];
      if (colours.length === 1) colour = cleanColour(colours[0]);
    }
    if (!colour) colour = "Other images";
    if (!groups.has(colour)) groups.set(colour, []);
    groups.get(colour).push(item);
  }
  return [...groups].map(([colour, images]) => ({ colour, images }));
}
export function measurementGroups(variants = []) {
  const groups = new Map();
  for (const v of variants) {
    const m = v.export_measurements || {};
    const weight = safeNumber(m.weight);
    const dims = [
      m.dimensions_length,
      m.dimensions_width,
      m.dimensions_height,
    ].map(safeNumber);
    const error = !!v.measurement_error;
    const key = JSON.stringify([weight, ...dims, error]);
    if (!groups.has(key))
      groups.set(key, {
        weight,
        dims,
        error,
        count: 0,
        sizes: new Set(),
        colours: new Set(),
      });
    const group = groups.get(key);
    group.count++;
    if (v.size) group.sizes.add(v.size);
    if (v.color) group.colours.add(v.color);
  }
  return [...groups.values()].map((g) => ({
    ...g,
    sizes: [...g.sizes],
    colours: [...g.colours],
  }));
}
export function resultMessages(value) {
  const messages = [];
  function visit(v, key = "", depth = 0) {
    if (depth > 8 || v == null) return;
    if (
      typeof v === "string" &&
      /error|message|warning|detail/i.test(key) &&
      v.trim()
    ) {
      if (v.trim().startsWith("{")) {
        try {
          visit(JSON.parse(v), key, depth + 1);
          return;
        } catch {}
      }
      messages.push(v.trim());
    } else if (Array.isArray(v)) v.forEach((x) => visit(x, key, depth + 1));
    else if (typeof v === "object")
      Object.entries(v).forEach(([k, x]) => visit(x, k, depth + 1));
  }
  visit(value);
  return [...new Set(messages)];
}

export function availableOptions(variants = []) {
  const aliases = {
    SMALL: "S",
    MEDIUM: "M",
    LARGE: "L",
    EXTRASMALL: "XS",
    EXTRALARGE: "XL",
    OS: "One size",
    OSFA: "One size",
    OSFM: "One size",
    ONESIZE: "One size",
  };
  function sizeLabel(value) {
    const source = String(value || "").trim(),
      key = source.toUpperCase().replace(/[\s_-]+/g, "");
    if (aliases[key]) return aliases[key];
    const repeated = key.match(/^(X+)(S|L)$/);
    if (repeated)
      return (
        (repeated[1].length === 1 ? "" : repeated[1].length) + "X" + repeated[2]
      );
    return source;
  }
  function rank(value) {
    const key = value.toUpperCase();
    let m = key.match(/^(\d*)XS$/);
    if (m) return [0, -Number(m[1] || 1)];
    if (["S", "M", "L"].includes(key)) return [0, { S: 0, M: 1, L: 2 }[key]];
    m = key.match(/^(\d*)XL$/);
    if (m) return [0, 2 + Number(m[1] || 1)];
    if (value === "One size") return [2, 0];
    return [/\d/.test(value) ? 1 : 3, 0];
  }
  const rows = variants.filter((v) => v.is_active !== false),
    colours = new Map(),
    sizes = new Map();
  for (const row of rows) {
    const colour = cleanColour(row.color),
      size = sizeLabel(row.size);
    if (colour && !["n/a", "na", "none", "null"].includes(colour.toLowerCase()))
      colours.set(colour.toLowerCase(), colour);
    if (size && !["n/a", "na", "none", "null"].includes(size.toLowerCase()))
      sizes.set(size.toLowerCase(), size);
  }
  return {
    colours: [...colours.values()].sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }),
    ),
    sizes: [...sizes.values()].sort((a, b) => {
      const x = rank(a),
        y = rank(b);
      return (
        x[0] - y[0] ||
        x[1] - y[1] ||
        a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" })
      );
    }),
  };
}
