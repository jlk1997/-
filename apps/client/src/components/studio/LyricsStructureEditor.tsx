import { useMemo, useState } from "react";
import { Textarea, View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import {
  LYRICS_BODY_LIMIT,
  STRUCTURE_TAGS,
  TEMPLATE_MINUTES,
  lyricsBodyLength,
  parseSections,
  serializeSections,
  templateLyrics,
  type LyricSection,
} from "@vibe-sorcery/types";
import "./LyricsStructureEditor.scss";

type Props = {
  lyrics: string;
  onChange: (lyrics: string) => void;
  onGenerate?: () => void;
  generating?: boolean;
  onReviseSection?: (instruction: string, sectionIndex: number) => void;
  revising?: boolean;
};

export function LyricsStructureEditor({
  lyrics,
  onChange,
  onGenerate,
  generating = false,
  onReviseSection,
  revising = false,
}: Props) {
  const { copy } = useLocale();
  const c = copy.createUi;
  const sections = useMemo(() => parseSections(lyrics), [lyrics]);
  const [active, setActive] = useState(0);
  const count = lyricsBodyLength(serializeSections(sections));

  function commit(next: LyricSection[]) {
    onChange(serializeSections(next));
  }

  function update(index: number, patch: Partial<LyricSection>) {
    commit(sections.map((section, i) => (i === index ? { ...section, ...patch } : section)));
  }

  function move(index: number, dir: -1 | 1) {
    const target = index + dir;
    if (target < 0 || target >= sections.length) return;
    const next = sections.slice();
    const [row] = next.splice(index, 1);
    next.splice(target, 0, row);
    commit(next);
    setActive(target);
  }

  return (
    <View className="lyrics-structure">
      <View className="lyrics-structure__head">
        <Text className="lyrics-structure__count">
          {c.lyricsCount} {count}/{LYRICS_BODY_LIMIT}
        </Text>
        <View className="lyrics-structure__templates">
          {Object.keys(TEMPLATE_MINUTES).map((name) => (
            <Text
              key={name}
              className="lyrics-structure__chip"
              onClick={() => onChange(templateLyrics(name))}
            >
              {c.structureTemplate} · {c.templateMinutes.replace("{n}", String(TEMPLATE_MINUTES[name]))}
            </Text>
          ))}
        </View>
      </View>
      {sections.map((section, index) => (
        <View key={`${section.tag}-${index}`} className="lyrics-structure__card">
          <View className="lyrics-structure__tags">
            {STRUCTURE_TAGS.map((tag) => (
              <Text
                key={tag}
                className={`lyrics-structure__chip ${section.tag === tag ? "lyrics-structure__chip--on" : ""}`}
                onClick={() => update(index, { tag })}
              >
                {tag}
              </Text>
            ))}
          </View>
          <Textarea
            className="lyrics-structure__text"
            value={section.text}
            maxlength={LYRICS_BODY_LIMIT}
            onInput={(event) => update(index, { text: event.detail.value })}
            onFocus={() => setActive(index)}
          />
          <View className="lyrics-structure__ops">
            <Text className="lyrics-structure__chip" onClick={() => move(index, -1)}>{c.structureUp}</Text>
            <Text className="lyrics-structure__chip" onClick={() => move(index, 1)}>{c.structureDown}</Text>
            <Text
              className="lyrics-structure__chip"
              onClick={() => commit(sections.filter((_, i) => i !== index).length ? sections.filter((_, i) => i !== index) : [{ tag: "Verse", text: "" }])}
            >
              {c.structureRemove}
            </Text>
            {onReviseSection && active === index && (
              <Text className="lyrics-structure__chip" onClick={() => onReviseSection("改得更口语、更适合演唱", index)}>
                {revising ? "…" : c.generateLyrics}
              </Text>
            )}
          </View>
        </View>
      ))}
      <View className="lyrics-structure__ops">
        <Text className="lyrics-structure__chip" onClick={() => commit([...sections, { tag: "Chorus", text: "" }])}>
          {c.structureAdd}
        </Text>
        {onGenerate && (
          <Text className="lyrics-structure__chip" onClick={onGenerate}>
            {generating ? "…" : c.generateLyrics}
          </Text>
        )}
      </View>
    </View>
  );
}
