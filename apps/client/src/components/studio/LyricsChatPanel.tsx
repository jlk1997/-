import { useMemo, useState } from "react";
import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { Button, TextArea, Input } from "../ui";
import "./LyricsChatPanel.scss";

type Props = {
  theme: string;
  lyrics: string;
  generating?: boolean;
  revising?: boolean;
  onThemeChange?: (theme: string) => void;
  onLyricsChange: (lyrics: string) => void;
  onGenerate: () => void;
  onRevise?: (instruction: string, lineIndex?: number) => void;
};

function splitLines(lyrics: string) {
  return lyrics.split(/\r?\n/);
}

export function LyricsChatPanel({
  theme,
  lyrics,
  generating,
  revising,
  onThemeChange,
  onLyricsChange,
  onGenerate,
  onRevise,
}: Props) {
  const { copy } = useLocale();
  const c = copy.createUi;
  const [instruction, setInstruction] = useState("");
  const [editingLine, setEditingLine] = useState<number | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const lines = useMemo(() => splitLines(lyrics), [lyrics]);

  function pushHistory(next: string) {
    if (!lyrics.trim() || lyrics === next) return;
    setHistory((prev) => [lyrics, ...prev].slice(0, 6));
  }

  function changeLine(index: number, value: string) {
    const next = [...lines];
    next[index] = value;
    const joined = next.join("\n");
    pushHistory(joined);
    onLyricsChange(joined);
  }

  return (
    <View className="lyrics-chat">
      <Text className="lyrics-chat__title">{c.lyricsChatTitle}</Text>
      <Text className="lyrics-chat__hint">{c.lyricsChatHint}</Text>
      {onThemeChange && (
        <TextArea
          label={c.intentLabel}
          placeholder={c.oneBoxPlaceholder}
          value={theme}
          onInput={(e) => onThemeChange(e.detail.value)}
          maxlength={300}
        />
      )}
      <View className="lyrics-chat__actions">
        <Button variant="secondary" size="sm" loading={generating} onClick={onGenerate}>
          {c.lyricsChatSend}
        </Button>
        {history[0] && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const prev = history[0];
              setHistory((h) => h.slice(1));
              onLyricsChange(prev);
            }}
          >
            {c.lyricsChatHistory}
          </Button>
        )}
      </View>
      {!lyrics.trim() && <Text className="typo-meta">{c.lyricsChatEmpty}</Text>}
      {lyrics.trim() && (
        <View className="lyrics-chat__draft">
          <Text className="lyrics-chat__line-hint">{c.lyricsChatLineHint}</Text>
          {lines.map((line, i) => (
            <View key={`${i}-${line.slice(0, 8)}`} className="lyrics-chat__line" onClick={() => setEditingLine(i)}>
              {editingLine === i ? (
                <Input
                  value={line}
                  onInput={(e) => changeLine(i, e.detail.value)}
                  onBlur={() => setEditingLine(null)}
                />
              ) : (
                <Text className="lyrics-chat__line-text">{line || " "}</Text>
              )}
            </View>
          ))}
        </View>
      )}
      {onRevise && lyrics.trim() && (
        <View className="lyrics-chat__revise">
          <Input
            placeholder={c.lyricsChatRevise}
            value={instruction}
            onInput={(e) => setInstruction(e.detail.value)}
          />
          <Button
            variant="ghost"
            size="sm"
            loading={revising}
            disabled={!instruction.trim()}
            onClick={() => {
              onRevise(instruction.trim(), editingLine ?? undefined);
              setInstruction("");
            }}
          >
            {c.lyricsChatRevise}
          </Button>
        </View>
      )}
    </View>
  );
}
