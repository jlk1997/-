import { View } from "@tarojs/components";
import { clsx } from "../../utils/clsx";
import "./PresetSigil.scss";

const MARKS: Record<string, string> = {
  "lo-fi-night": `<path fill="#fff" d="M14.2 3.4a6.8 6.8 0 1 0 4.6 12.2 5.4 5.4 0 0 1-4.6-12.2z"/>`,
  "calm-focus": `<circle cx="12" cy="12" r="6.2" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="12" cy="12" r="1.7" fill="#fff"/>`,
  "energy-rise": `<path fill="#fff" d="M13.2 2.2 5.6 13h4.6L9.4 21.8 18.4 10h-4.4z"/>`,
  cinematic: `<path fill="#fff" fill-rule="evenodd" d="M4 6.2h16v11.6H4V6.2zm1.8 1.8v8h12.4v-8H5.8z"/><path fill="#fff" d="M7.2 4.2h2.2v2H7.2zm7.4 0h2.2v2h-2.2zM7.2 17.8h2.2v2H7.2zm7.4 0h2.2v2h-2.2z"/>`,
  "pop-vocal": `<path fill="#fff" d="M9.2 17.6a2.3 2.3 0 1 1 .1-4.6V6.1l7.6-1.4v8.2a2.3 2.3 0 1 1-1.6-2.2V7.2l-4.4.8v7.3a2.3 2.3 0 0 1-1.7 2.3z"/>`,
  "alchemist-vip": `<path fill="none" stroke="#fff" stroke-width="1.7" d="M12 3.2 19 7.2v7.6L12 20.8 5 14.8V7.2z"/>`,
  default: `<circle cx="12" cy="12" r="6" fill="none" stroke="#fff" stroke-width="1.8"/>`,
};

type Props = {
  presetId?: string | null;
  size?: "sm" | "md" | "lg";
  active?: boolean;
  className?: string;
};

function markFor(id?: string | null): string {
  if (!id) return MARKS.default;
  if (MARKS[id]) return MARKS[id];
  const key = id.toLowerCase();
  if (key.includes("lofi") || key.includes("lo-fi") || key.includes("night")) return MARKS["lo-fi-night"];
  if (key.includes("calm") || key.includes("focus")) return MARKS["calm-focus"];
  if (key.includes("energy") || key.includes("rise")) return MARKS["energy-rise"];
  if (key.includes("cinematic") || key.includes("film")) return MARKS.cinematic;
  if (key.includes("pop") || key.includes("vocal")) return MARKS["pop-vocal"];
  if (key.includes("alchem") || key.includes("vip")) return MARKS["alchemist-vip"];
  return MARKS.default;
}

/** Centered style mark drawn inside the preset color tile. */
export function PresetSigil({ presetId, size = "md", active, className }: Props) {
  const body = markFor(presetId);
  const src = `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">${body}</svg>`
  )}`;
  return (
    <View className={clsx("preset-sigil", `preset-sigil--${size}`, active && "preset-sigil--active", className)}>
      <View className="preset-sigil__icon" style={{ backgroundImage: `url("${src}")` }} />
    </View>
  );
}
