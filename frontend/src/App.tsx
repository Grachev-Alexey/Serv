import { Routes, Route, Navigate } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import CameraPage from "./pages/CameraPage";
import SettingsPage from "./pages/SettingsPage";

function Splash() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <div className="grid h-14 w-14 animate-pulse place-items-center rounded-2xl bg-brand/15 ring-1 ring-brand/30">
        <ShieldCheck className="h-7 w-7 text-brand" />
      </div>
      <div className="text-sm text-ink-muted">Загрузка…</div>
    </div>
  );
}

export default function App() {
  const { username, loading } = useAuth();

  if (loading) return <Splash />;

  return (
    <Routes>
      <Route
        path="/login"
        element={username ? <Navigate to="/" replace /> : <Login />}
      />
      <Route
        path="/"
        element={username ? <Dashboard /> : <Navigate to="/login" replace />}
      />
      <Route
        path="/camera/:deviceId"
        element={username ? <CameraPage /> : <Navigate to="/login" replace />}
      />
      <Route
        path="/settings"
        element={username ? <SettingsPage /> : <Navigate to="/login" replace />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
