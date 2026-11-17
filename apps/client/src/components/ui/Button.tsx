import { Button as TaroButton, ButtonProps, View } from "@tarojs/components";
import { clsx } from "../../utils/clsx";
import "./ui.scss";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "md" | "sm";

type Props = Omit<ButtonProps, "size"> & {
  variant?: Variant;
  size?: Size;
  block?: boolean;
};

const isH5 = process.env.TARO_ENV === "h5";

export function Button({
  variant = "primary",
  size = "md",
  block,
  className,
  children,
  loading,
  disabled,
  onClick,
  ...rest
}: Props) {
  const busy = !!loading;
  const locked = !!disabled || busy;
  const cls = clsx(
    "ui-btn",
    `ui-btn--${variant}`,
    size === "sm" && "ui-btn--sm",
    block && "ui-btn--block",
    busy && "ui-btn--busy",
    locked && "ui-btn--disabled",
    className
  );

  // WeChat in-app browser often swallows taps on <button> / taro-button-core.
  if (isH5) {
    return (
      <View
        className={cls}
        hoverClass="none"
        onClick={(event) => {
          if (locked) return;
          onClick?.(event);
        }}
      >
        {busy ? <View className="ui-btn__spinner" aria-hidden /> : null}
        {children}
      </View>
    );
  }

  return (
    <TaroButton className={cls} disabled={locked} loading={busy} onClick={onClick} {...rest}>
      {children}
    </TaroButton>
  );
}
