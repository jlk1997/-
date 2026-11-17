import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Taro from "@tarojs/taro";
import { vibeApi, isUnauthorized } from "../services/api";
import { getToken } from "../platform/storage";

type CreditsSubscription = {
  status?: string;
  monthly_credits?: number;
  days_remaining?: number | null;
  can_manage_stripe?: boolean;
  cancel_at_period_end?: boolean;
} | null;

type CreditsContextValue = {
  balance: number | null;
  gateEnabled: boolean;
  loading: boolean;
  ready: boolean;
  isMember: boolean;
  subscription: CreditsSubscription;
  refresh: () => Promise<void>;
  refreshFlags: () => Promise<void>;
  setBalance: (balance: number) => void;
  flags: Record<string, boolean>;
  dspDistribution: boolean;
  royaltyWallet: boolean;
};

const CreditsContext = createContext<CreditsContextValue | null>(null);

export function CreditsProvider({ children }: { children: ReactNode }) {
  const [balance, setBalance] = useState<number | null>(null);
  const [gateEnabled, setGateEnabled] = useState(false);
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [isMember, setIsMember] = useState(false);
  const [subscription, setSubscription] = useState<CreditsSubscription>(null);

  const lastFlagsAt = useRef(0);
  const lastRefreshAt = useRef(0);
  const balanceRef = useRef<number | null>(null);

  const refreshFlags = useCallback(async (force = false) => {
    if (!force && lastFlagsAt.current && Date.now() - lastFlagsAt.current < 60_000) return;
    try {
      const next = await vibeApi.getFeatureFlags();
      const resolved = next || {};
      setFlags(resolved);
      setGateEnabled(Boolean(resolved.credits_gate));
      lastFlagsAt.current = Date.now();
    } catch (err) {
      console.warn("[credits] getFeatureFlags failed:", err);
    }
  }, []);

  useEffect(() => {
    void refreshFlags();
    const onShow = () => {
      void refreshFlags();
    };
    Taro.onAppShow(onShow);
    return () => {
      try {
        Taro.offAppShow(onShow);
      } catch {
        /* older runtimes */
      }
    };
  }, [refreshFlags]);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setBalance(null);
      setIsMember(false);
      setSubscription(null);
      return;
    }
    if (lastRefreshAt.current && Date.now() - lastRefreshAt.current < 20_000 && balanceRef.current !== null) {
      return;
    }
    setLoading(true);
    try {
      const [res, sub] = await Promise.all([
        vibeApi.getCredits(),
        vibeApi.getSubscription().catch(() => null),
      ]);
      setBalance(res.balance);
      balanceRef.current = res.balance;
      lastRefreshAt.current = Date.now();
      setIsMember(sub?.status === "active" || sub?.tier === "member");
      setSubscription(sub);
    } catch (err) {
      if (!isUnauthorized(err)) {
        setBalance(null);
        setIsMember(false);
        setSubscription(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const ready = !loading && balance !== null;
  const dspDistribution = flags.dsp_distribution !== false;
  const royaltyWallet = flags.royalty_wallet !== false;

  const value = useMemo(
    () => ({
      balance,
      gateEnabled,
      loading,
      ready,
      isMember,
      subscription,
      refresh,
      refreshFlags,
      setBalance: (next: number) => setBalance(next),
      flags,
      dspDistribution,
      royaltyWallet,
    }),
    [balance, gateEnabled, loading, ready, isMember, subscription, refresh, refreshFlags, flags, dspDistribution, royaltyWallet]
  );

  return <CreditsContext.Provider value={value}>{children}</CreditsContext.Provider>;
}

export function useCredits() {
  const ctx = useContext(CreditsContext);
  if (!ctx) throw new Error("useCredits must be used within CreditsProvider");
  return ctx;
}

export function useCreditsOptional() {
  return useContext(CreditsContext);
}
