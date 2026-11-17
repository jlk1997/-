import { lazy, Suspense } from "react";
import { LoadingSkeleton } from "../../components/ui";
import "../../styles/tab-page.scss";
import "./index.scss";

const CreatorDesk = lazy(() =>
  import("../../packageCreator/CreatorDesk").then((m) => ({ default: m.CreatorDesk })),
);

export default function CreatorTabPage() {
  return (
    <Suspense fallback={<LoadingSkeleton count={4} />}>
      <CreatorDesk tabVariant />
    </Suspense>
  );
}
