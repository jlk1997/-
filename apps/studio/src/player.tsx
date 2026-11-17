import { createContext, useContext, useMemo, useRef, useState, type ReactNode } from "react";

export type DeskTrack = { id: string; title: string; url: string; cover?: string };

type PlayerApi = {
  track: DeskTrack | null;
  playing: boolean;
  play: (track: DeskTrack) => void;
  toggle: () => void;
  stop: () => void;
};

const Ctx = createContext<PlayerApi | null>(null);

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [track, setTrack] = useState<DeskTrack | null>(null);
  const [playing, setPlaying] = useState(false);

  const api = useMemo<PlayerApi>(() => {
    const element = () => {
      if (!audio.current) {
        audio.current = new Audio();
        audio.current.onended = () => setPlaying(false);
      }
      return audio.current;
    };
    return {
      track,
      playing,
      play: (next) => {
        const node = element();
        if (track?.id !== next.id) {
          node.src = next.url;
          setTrack(next);
        }
        void node.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      },
      toggle: () => {
        const node = element();
        if (!track) return;
        if (node.paused) void node.play().then(() => setPlaying(true));
        else {
          node.pause();
          setPlaying(false);
        }
      },
      stop: () => {
        element().pause();
        setPlaying(false);
        setTrack(null);
      },
    };
  }, [playing, track]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useDeskPlayer() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("player");
  return ctx;
}
