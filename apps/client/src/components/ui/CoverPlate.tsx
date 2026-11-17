import { Text, View } from "@tarojs/components";
import { clsx } from "../../utils/clsx";
import "./CoverPlate.scss";

const PLATES: Array<[string, string]> = [
  ["#4a342c", "#1c1412"],
  ["#2c3d52", "#121820"],
  ["#2a4034", "#121814"],
  ["#463052", "#18141c"],
  ["#4a3c28", "#18160f"],
  ["#274044", "#101618"],
];

function hashSeed(seed: string): number {
  let n = 0;
  for (let i = 0; i < seed.length; i += 1) n = (n * 33 + seed.charCodeAt(i)) >>> 0;
  return n;
}

type Props = {
  title: string;
  seed?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
};

/** Designed plate used when a song has no cover image. */
export function CoverPlate({ title, seed, size = "md", className }: Props) {
  const key = (seed || title || "song").trim() || "song";
  const [from, to] = PLATES[hashSeed(key) % PLATES.length];
  const mark = (title || "音").trim().slice(0, 1) || "音";
  return (
    <View
      className={clsx("cover-plate", `cover-plate--${size}`, className)}
      style={{ background: `linear-gradient(160deg, ${from} 0%, ${to} 100%)` }}
    >
      <Text className="cover-plate__mark">{mark}</Text>
    </View>
  );
}
