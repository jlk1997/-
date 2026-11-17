/** Mirror of backend/app/core/lyrics_structure.py. Tags do not count toward the 3500 limit. */

export const STRUCTURE_TAGS = [
  "Intro",
  "Verse",
  "Pre Chorus",
  "Chorus",
  "Interlude",
  "Bridge",
  "Outro",
  "Post Chorus",
  "Transition",
  "Break",
  "Hook",
  "Build Up",
  "Inst",
  "Solo",
] as const;

export type StructureTag = (typeof STRUCTURE_TAGS)[number];

const CANONICAL = new Map(STRUCTURE_TAGS.map((tag) => [tag.toLowerCase(), tag]));

const ALIASES: Record<string, string> = {
  prechorus: "pre chorus",
  "pre-chorus": "pre chorus",
  postchorus: "post chorus",
  "post-chorus": "post chorus",
  buildup: "build up",
  "build-up": "build up",
  "verse 1": "verse",
  "verse 2": "verse",
  verse1: "verse",
  verse2: "verse",
};

export const STRUCTURE_TEMPLATES: Record<string, StructureTag[]> = {
  short: ["Intro", "Verse", "Chorus", "Outro"],
  standard: ["Intro", "Verse", "Pre Chorus", "Chorus", "Verse", "Chorus", "Bridge", "Chorus", "Outro"],
  full: ["Intro", "Verse", "Pre Chorus", "Chorus", "Verse", "Pre Chorus", "Chorus", "Bridge", "Chorus", "Solo", "Chorus", "Outro"],
  instrumental: ["Intro", "Build Up", "Hook", "Break", "Hook", "Outro"],
};

export const TEMPLATE_MINUTES: Record<string, number> = {
  short: 1,
  standard: 3,
  full: 4,
  instrumental: 2,
};

export const LYRICS_BODY_LIMIT = 3500;
export const PROMPT_LIMIT = 2000;

const TAG_RE = /\[([^\]\n]+)\]/g;

export function canonicalLabel(label: string): string | null {
  const key = label.trim().toLowerCase().replace(/\s+/g, " ");
  const aliased = ALIASES[key] || ALIASES[key.replace(/ /g, "")] || key;
  return CANONICAL.get(aliased) || null;
}

export function lyricsBodyLength(lyrics: string): number {
  const body = (lyrics || "").replace(TAG_RE, (full, inner: string) => (canonicalLabel(inner) ? "" : full)).trim();
  return body.length;
}

export function stripStructureTags(lyrics: string): string {
  return (lyrics || "")
    .split("\n")
    .map((line) => line.replace(TAG_RE, (full, inner: string) => (canonicalLabel(inner) ? "" : full)).trim())
    .filter(Boolean)
    .join("\n");
}

export type LyricSection = { tag: string; text: string };

export function parseSections(lyrics: string): LyricSection[] {
  const source = (lyrics || "").replace(/\r\n/g, "\n");
  if (!source.trim()) return [{ tag: "Verse", text: "" }];
  const parts = source.split(/(\[[^\]\n]+\])/g);
  const sections: LyricSection[] = [];
  let pending = "";
  for (const part of parts) {
    const tagMatch = part.match(/^\[([^\]\n]+)\]$/);
    const canon = tagMatch ? canonicalLabel(tagMatch[1]) : null;
    if (canon) {
      if (pending.trim() && sections.length === 0) {
        sections.push({ tag: "Verse", text: pending.trim() });
      }
      sections.push({ tag: canon, text: "" });
      pending = "";
      continue;
    }
    if (sections.length === 0) {
      pending += part;
      continue;
    }
    sections[sections.length - 1].text += part;
  }
  if (!sections.length) return [{ tag: "Verse", text: source.trim() }];
  return sections.map((section) => ({ tag: section.tag, text: section.text.replace(/^\n+|\n+$/g, "") }));
}

export function serializeSections(sections: LyricSection[]): string {
  return sections
    .map((section) => {
      const body = section.text.replace(/\s+$/g, "");
      return body ? `[${section.tag}]\n${body}` : `[${section.tag}]`;
    })
    .join("\n")
    .trim();
}

export function templateLyrics(name: string): string {
  const tags = STRUCTURE_TEMPLATES[name] || STRUCTURE_TEMPLATES.standard;
  return tags.map((tag) => `[${tag}]\n`).join("\n");
}
