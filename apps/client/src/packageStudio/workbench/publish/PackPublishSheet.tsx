import { Text, Input } from "@tarojs/components";
import { BottomSheet, Button, ChipGroup } from "../../../components/ui";
import { NEED_OPTIONS } from "../types";
import type { WorkbenchModel } from "../hooks/useWorkbenchSession";

export function PackPublishSheet({ model }: { model: WorkbenchModel }) {
  const w = model.w;
  const applied = model.packs.find((pack) => pack.id === model.session?.applied_pack_id);
  return (
    <BottomSheet open={model.publishOpen} onClose={() => model.setPublishOpen(false)} title={w.publishPack}>
      <Text className="typo-meta">{w.publishHasClips}</Text>
      <Text className="typo-meta">{w.publishNoExternal}</Text>
      <Input className="wb-pub-input" placeholder={w.publishTitle} value={model.pubTitle} onInput={(e) => model.setPubTitle(e.detail.value)} />
      <Input className="wb-pub-input" placeholder={w.publishDesc} value={model.pubDesc} onInput={(e) => model.setPubDesc(e.detail.value)} />
      <Text className="typo-meta">{w.publishNeeds}</Text>
      <ChipGroup
        value={model.pubNeeds[0] || "none"}
        onChange={(value) => model.setPubNeeds(value === "none" ? [] : [value])}
        options={[
          { value: "none", label: w.packsOfficial },
          ...NEED_OPTIONS.map((item) => ({ value: item.id, label: String(w[item.label]) })),
        ]}
      />
      <ChipGroup
        value={model.pubKind}
        onChange={model.setPubKind}
        options={[
          { value: "scene", label: w.publishKindScene },
          { value: "lane", label: w.publishKindLane },
        ]}
      />
      <Text className="typo-meta">{w.publishPrice}</Text>
      <ChipGroup
        value={model.pubPrice}
        onChange={model.setPubPrice}
        options={[
          { value: "0", label: model.copy.marketplaceUi.free },
          { value: "3", label: "3" },
          { value: "8", label: "8" },
        ]}
      />
      {applied ? (
        <Button size="sm" variant="ghost" loading={model.busy === `preview-${applied.id}`} onClick={() => void model.onPreview(applied)}>
          {w.previewPack}
        </Button>
      ) : null}
      <Button variant="primary" block loading={model.busy === "publish"} onClick={() => void model.onPublish()}>
        {w.publishPack}
      </Button>
      <Text className="typo-meta">{w.publishPending}</Text>
    </BottomSheet>
  );
}
