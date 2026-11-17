import type { Copy } from "@vibe-sorcery/i18n";
import { creatorPage, socialPage, stackPage } from "../constants/routes";
import { goShipBand } from "../packageCreator/nextActionNav";
import { resolveWorkCoreDoor, type WorkDoorInput } from "./workbenchWorks";
import { openRadioPage, openStackPage } from "./navigation";
import { openWorkbench } from "./workbenchNav";
import type { CoreDoor } from "./nextCoreDoor";

export function coreDoorActionLabel(door: CoreDoor, copy: Copy): string {
  if (door === "beautify") return copy.generation.reveal.beautify;
  if (door === "release") return copy.generation.reveal.releaseThisVersion;
  if (door === "deliveries") return copy.creatorUi.goDeliveries;
  if (door === "fix") return copy.generation.postProcessFix;
  return copy.generation.reveal.radioNext;
}

/** Navigate the shared post-listen door: beautify A, or ship / fix / radio B. */
export function goWorkCoreDoor<T extends WorkDoorInput>(work: T, works: T[] = []): void {
  const { door, workId, sourceId } = resolveWorkCoreDoor(work, works);
  if (door === "beautify") {
    openWorkbench(sourceId);
    return;
  }
  if (door === "fix") {
    openStackPage(stackPage("work", { workId }));
    return;
  }
  if (door === "release") {
    goShipBand(workId);
    return;
  }
  if (door === "deliveries") {
    openStackPage(creatorPage("deliveries", { workId }));
    return;
  }
  openRadioPage({ workId });
}
