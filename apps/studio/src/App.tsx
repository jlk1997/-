import { ApiError, vibeApi } from "@vibe-sorcery/api-client";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { deskCopy } from "./copy";
import { DeskShell } from "./shell/DeskShell";
import { PlayerProvider } from "./player";
import { AccountPage } from "./pages/AccountPage";
import { CreatePage } from "./pages/CreatePage";
import { DiscoverPage } from "./pages/DiscoverPage";
import { LibraryPage } from "./pages/LibraryPage";
import { LoginPage } from "./pages/LoginPage";
import { MixerPage } from "./pages/MixerPage";
import { ReleasePage } from "./pages/ReleasePage";

function Gate() {
  const location = useLocation();
  const copy = deskCopy();
  const me = useQuery({ queryKey: ["me"], queryFn: () => vibeApi.me(), retry: false, enabled: location.pathname !== "/login" });
  if (location.pathname === "/login") return <LoginPage />;
  if (me.isLoading) return <div className="boot">{copy.brand}</div>;
  if (me.isError) {
    const status = me.error instanceof ApiError ? me.error.status : 0;
    if (status === 401) return <Navigate to="/login" replace />;
    return (
      <div className="boot">
        <p>工作室暂时打不开</p>
        <button type="button" onClick={() => void me.refetch()}>重试</button>
      </div>
    );
  }
  return (
    <DeskShell username={me.data?.username || me.data?.display_name || ""}>
      <Routes>
        <Route path="/" element={<Navigate to="/create" replace />} />
        <Route path="/create" element={<CreatePage />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/mixer" element={<MixerPage />} />
        <Route path="/release" element={<ReleasePage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/discover" element={<DiscoverPage />} />
        <Route path="*" element={<Navigate to="/create" replace />} />
      </Routes>
    </DeskShell>
  );
}

export function App() {
  return (
    <PlayerProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/*" element={<Gate />} />
      </Routes>
    </PlayerProvider>
  );
}
