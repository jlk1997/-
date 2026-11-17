import Taro from "@tarojs/taro";
import { PageShell } from "../../components/PageShell";
import { Button, EmptyState, LoadingSkeleton } from "../../components/ui";
import { stackPage } from "../../constants/routes";
import { useWorkbenchSession } from "./hooks/useWorkbenchSession";
import { LiteConsole } from "./shells/LiteConsole";
import { isWeapp, type Variant } from "./types";
import "./workbench.scss";

export function WorkbenchDesk({ variant }: { variant: Variant }) {
  const model = useWorkbenchSession(variant);
  const w = model.w;
  return (
    <PageShell
      title={w.liteTitle}
      subtitle={w.liteSubtitle}
      wide
      ambient
      actions={
        !isWeapp && model.workId ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const id = model.session?.source_work_id || model.workId;
              const url = `https://superformersmusic.com/studio/mixer?work=${id}`;
              if (typeof window !== "undefined") window.open(url, "_blank");
            }}
          >
            {w.openDesktopMixer}
          </Button>
        ) : undefined
      }
    >
      {model.loading && <LoadingSkeleton count={4} />}
      {!model.loading && !model.workId && (
        <EmptyState
          iconName="sparkle"
          title={w.needWork}
          description={w.needWorkHint}
          actionLabel={w.needWorkCta}
          onAction={() => Taro.switchTab({ url: "/pages/create/index" })}
        />
      )}
      {!model.loading && model.workId && !model.session && (
        <EmptyState
          iconName="sparkle"
          title={w.needLogin}
          description={w.needLoginHint}
          actionLabel={w.needLoginCta}
          onAction={() => Taro.navigateTo({ url: stackPage("login") })}
        />
      )}
      {model.session ? <LiteConsole model={model} /> : null}
    </PageShell>
  );
}
