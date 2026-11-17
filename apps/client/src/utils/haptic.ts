import Taro from "@tarojs/taro";

/** Light haptic for confirmations. Never throws — WeChat / H5 may ignore it. */
export function hapticLight() {
  Taro.vibrateShort({ type: "light" }).catch(() => undefined);
}

export function hapticMedium() {
  Taro.vibrateShort({ type: "medium" }).catch(() => undefined);
}
