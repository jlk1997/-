import { View } from "@tarojs/components";
import { clsx } from "../../utils/clsx";
import "./AtmosphereLayer.scss";

type Props = {
  variant?: "default" | "warm" | "cool" | "preset";
  intensity?: "low" | "medium" | "high";
  className?: string;
};

/** Phones with few cores or little memory should not pay for a full-screen blur. */
function preferFlatAtmosphere(): boolean {
  if (process.env.TARO_ENV === "weapp") return true;
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { deviceMemory?: number };
  if (typeof nav.deviceMemory === "number" && nav.deviceMemory > 0 && nav.deviceMemory <= 4) return true;
  if (typeof nav.hardwareConcurrency === "number" && nav.hardwareConcurrency > 0 && nav.hardwareConcurrency <= 4) {
    return true;
  }
  try {
    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return true;
  } catch {
    return false;
  }
  return false;
}

/** Ethereal atmosphere — gold/ether orbs driven by CSS vars */
export function AtmosphereLayer({ variant = "default", intensity = "medium", className }: Props) {
  const weapp = process.env.TARO_ENV === "weapp";
  const flat = preferFlatAtmosphere();
  return (
    <View
      className={clsx(
        "ui-atmosphere",
        `ui-atmosphere--${variant}`,
        `ui-atmosphere--${intensity}`,
        (weapp || flat) && "ui-atmosphere--static",
        flat && "ui-atmosphere--flat",
        className
      )}
      aria-hidden
    >
      <View className="ui-atmosphere__veil" />
      {!weapp ? (
        <>
          <View className="ui-atmosphere__orb ui-atmosphere__orb--1" />
          <View className="ui-atmosphere__orb ui-atmosphere__orb--2" />
          <View className="ui-atmosphere__orb ui-atmosphere__orb--3" />
          <View className="ui-atmosphere__grain" />
        </>
      ) : null}
      <View className="ui-atmosphere__vignette" />
    </View>
  );
}

/** @deprecated Use AtmosphereLayer */
export { AtmosphereLayer as AmbientMesh };
