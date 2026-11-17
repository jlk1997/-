import { View, Text } from "@tarojs/components";
import { StatusLine } from "../components/ui";
import { mapSeatError, seatPhase } from "./lib";

export type SeatLamp = {
  id?: string;
  ownership?: string;
  channel_code: string;
  status?: string;
  last_harvest_at?: string | null;
  last_upload_at?: string | null;
  last_error?: string | null;
  has_session?: boolean;
  remote_status?: string;
  playbook?: { name?: string };
  farm_health?: {
    ok?: boolean;
    rows?: number;
    matched?: number;
    official_csv?: boolean;
    session_expired?: boolean;
    elapsed_ms?: number;
    handed_to_extension?: boolean;
    license_blocked?: boolean;
  };
  scopes?: { metrics?: boolean; settle?: boolean; keep_sync?: boolean; upload?: boolean } | null;
  last_sync_at?: string | null;
};

type SeatCopy = {
  seatLive: string;
  seatChallenge: string;
  seatExpired: string;
  seatConnecting: string;
  seatHarvestAt: string;
  seatWaitingHarvest?: string;
  seatHarvested?: string;
  seatNeedLoginName?: string;
  seatChallengeHint?: string;
  seatExpiredHint?: string;
  harvestFailHint?: string;
  seatFarmHealth?: string;
};

function toneFor(phase: ReturnType<typeof seatPhase>): "success" | "loading" | "error" | "info" {
  if (phase === "harvested") return "success";
  if (phase === "waiting_harvest") return "info";
  if (phase === "challenge" || phase === "expired") return "error";
  return "loading";
}

function labelFor(seat: SeatLamp, c: SeatCopy) {
  const name = seat.playbook?.name || seat.channel_code;
  const phase = seatPhase(seat);
  if (phase === "challenge") return c.seatChallenge.replace("{name}", name);
  if (phase === "expired") return c.seatExpired.replace("{name}", name);
  if (phase === "harvested") return (c.seatHarvested || c.seatLive).replace("{name}", name);
  if (phase === "waiting_harvest") return (c.seatWaitingHarvest || c.seatLive).replace("{name}", name);
  if (phase === "need_login") return (c.seatNeedLoginName || c.seatConnecting).replace("{name}", name);
  return c.seatConnecting.replace("{name}", name);
}

export function SeatLamps({
  seats,
  copy,
  ownership,
  onOpen,
}: {
  seats?: SeatLamp[] | null;
  copy: SeatCopy;
  ownership?: "platform" | "user";
  onOpen?: (seat: SeatLamp) => void;
}) {
  const rows = (seats || []).filter((row) => !ownership || row.ownership === ownership);
  if (!rows.length) return null;
  return (
    <View className="creator-seats">
      {rows.map((seat) => (
        <View
          key={seat.id || `${seat.ownership}-${seat.channel_code}`}
          className={onOpen ? "creator-seat creator-seat--tap" : "creator-seat"}
          onClick={onOpen ? () => onOpen(seat) : undefined}
        >
          <StatusLine tone={toneFor(seatPhase(seat))}>{labelFor(seat, copy)}</StatusLine>
          {seatPhase(seat) === "challenge" && copy.seatChallengeHint ? (
            <Text className="typo-meta">{copy.seatChallengeHint}</Text>
          ) : null}
          {seatPhase(seat) === "expired" && copy.seatExpiredHint ? (
            <Text className="typo-meta">{copy.seatExpiredHint}</Text>
          ) : null}
          {mapSeatError(seat.last_error, copy) ? (
            <Text className="typo-meta">{mapSeatError(seat.last_error, copy)}</Text>
          ) : null}
          {seat.last_harvest_at ? (
            <Text className="typo-meta">{copy.seatHarvestAt.replace("{t}", String(seat.last_harvest_at).slice(0, 16))}</Text>
          ) : null}
          {seat.farm_health && copy.seatFarmHealth ? (
            <Text className="typo-meta">
              {copy.seatFarmHealth
                .replace("{n}", String(seat.farm_health.matched ?? seat.farm_health.rows ?? 0))
                .replace("{src}", seat.farm_health.official_csv ? "CSV" : "DOM")}
            </Text>
          ) : null}
        </View>
      ))}
    </View>
  );
}
