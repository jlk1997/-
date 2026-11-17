import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import "./SongSetupBar.scss";

export type SongMode = "auto_lyrics" | "lyrics" | "instrumental";
export type FreedomLevel = "literal" | "balanced" | "open";
export type SongQuality = "standard" | "master";

type Props = {
  songMode: SongMode;
  freedom: FreedomLevel;
  takes: 1 | 2;
  quality: SongQuality;
  quick: boolean;
  onSongMode: (mode: SongMode) => void;
  onFreedom: (freedom: FreedomLevel) => void;
  onTakes: (takes: 1 | 2) => void;
  onQuality: (quality: SongQuality) => void;
  onQuick: (quick: boolean) => void;
  modesOnly?: boolean;
};

export function SongSetupBar(props: Props) {
  const { copy } = useLocale();
  const c = copy.createUi;
  return (
    <View className="song-setup">
      <View className="song-setup__group">
        {props.modesOnly ? null : <Text className="song-setup__label">{c.songModeLabel}</Text>}
        <View className="song-setup__row">
          <Chip on={props.songMode === "auto_lyrics"} label={c.songModeAuto} onClick={() => props.onSongMode("auto_lyrics")} />
          <Chip on={props.songMode === "lyrics"} label={c.songModeLyrics} onClick={() => props.onSongMode("lyrics")} />
          <Chip on={props.songMode === "instrumental"} label={c.songModeInst} onClick={() => props.onSongMode("instrumental")} />
        </View>
      </View>
      {props.modesOnly ? null : (
        <>
      <View className="song-setup__group">
        <Text className="song-setup__label">{c.freedomLabel}</Text>
        <View className="song-setup__row">
          <Chip on={props.freedom === "literal"} label={c.freedomLiteral} onClick={() => props.onFreedom("literal")} />
          <Chip on={props.freedom === "balanced"} label={c.freedomBalanced} onClick={() => props.onFreedom("balanced")} />
          <Chip on={props.freedom === "open"} label={c.freedomOpen} onClick={() => props.onFreedom("open")} />
        </View>
      </View>
      <View className="song-setup__group">
        <Text className="song-setup__label">{c.takesLabel}</Text>
        <View className="song-setup__row">
          <Chip on={props.takes === 1} label={c.takesOne} onClick={() => props.onTakes(1)} />
          <Chip on={props.takes === 2} label={c.takesTwo} onClick={() => props.onTakes(2)} />
        </View>
      </View>
      <View className="song-setup__group">
        <Text className="song-setup__label">{c.qualityLabel}</Text>
        <View className="song-setup__row">
          <Chip on={props.quality === "standard"} label={c.qualityStandard} onClick={() => props.onQuality("standard")} />
          <Chip on={props.quality === "master"} label={c.qualityMaster} onClick={() => props.onQuality("master")} />
        </View>
      </View>
      <View className="song-setup__hints">
        <Text className="song-setup__hint">{c.qualityMasterHint}</Text>
        <Text className="song-setup__hint">{c.vocalGuidance}</Text>
        {props.songMode === "auto_lyrics" && (
          <View className="song-setup__row">
            <Chip on={props.quick} label={c.quickSong} onClick={() => props.onQuick(!props.quick)} />
            <Text className="song-setup__hint">{props.quick ? c.quickSongHint : c.autoLyricsHint}</Text>
          </View>
        )}
      </View>
        </>
      )}
    </View>
  );
}

function Chip({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <Text className={`song-setup__chip ${on ? "song-setup__chip--on" : ""}`} onClick={onClick}>
      {label}
    </Text>
  );
}
