import { useEffect, useMemo, useState } from "react";
import { View, Text } from "@tarojs/components";
import { useLocale } from "@vibe-sorcery/i18n";
import { workToPlayerTrack } from "@vibe-sorcery/types";
import { vibeApi } from "../../services/api";
import { usePlayerTransport } from "../../contexts/PlayerProvider";
import { Button, LibraryShelf } from "../ui";
import "./OfficialListenShelf.scss";

export type OfficialCatalogTrack = {
  id: string;
  slug: string;
  title: string;
  caption?: string;
  moods?: string[];
  stations?: string[];
  audio_url: string;
  author?: string;
};

type Props = {
  station?: string;
  query?: string;
  title?: string;
};

export function OfficialListenShelf({ station, query, title }: Props) {
  const { copy } = useLocale();
  const { playTrack } = usePlayerTransport();
  const [tracks, setTracks] = useState<OfficialCatalogTrack[]>([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    vibeApi
      .listOfficialCatalog(station)
      .then((res) => {
        if (!alive) return;
        const needle = (query || "").trim().toLowerCase();
        const rows = (res.tracks || []).filter((row) => {
          if (!needle) return true;
          return (
            row.title.toLowerCase().includes(needle) ||
            row.slug.toLowerCase().includes(needle) ||
            (row.moods || []).some((mood) => mood.toLowerCase().includes(needle)) ||
            (row.caption || "").toLowerCase().includes(needle)
          );
        });
        setTracks(rows);
        setError(false);
      })
      .catch(() => {
        if (alive) {
          setTracks([]);
          setError(true);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [station, query, tick]);

  const queue = useMemo(
    () =>
      tracks.map((row) =>
        workToPlayerTrack(
          { id: row.id, title: row.title, audio_url: row.audio_url },
          { artist: row.author || copy.brand.name, source: "catalog" },
        ),
      ),
    [tracks, copy.brand.name],
  );

  if (!tracks.length) {
    return (
      <View className="official-listen">
        <Text className="official-listen__hint">{title || copy.discoverUi.officialShelf}</Text>
        <Text className="official-listen__hint">
          {error ? copy.discoverUi.loadError : copy.discoverUi.officialEmpty}
        </Text>
        <Button size="sm" variant="ghost" loading={loading} onClick={() => setTick((n) => n + 1)}>
          {copy.discoverUi.retry}
        </Button>
      </View>
    );
  }

  return (
    <View className="official-listen">
      <LibraryShelf
        label={title || copy.discoverUi.officialShelf}
        items={tracks.map((row) => ({ id: row.id, title: row.title }))}
        onSelect={(id) => {
          const index = queue.findIndex((track) => track.id === id);
          if (index < 0) return;
          playTrack(queue[index], { queue, startIndex: index, navigate: false });
        }}
      />
      <Text className="official-listen__hint">{copy.engagementUi.radioDiscoveryOnly}</Text>
    </View>
  );
}
