import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search, RefreshCw, Video, Wifi, WifiOff } from "lucide-react";
import { api } from "../api";
import AppShell from "../components/AppShell";
import DeviceCard from "../components/DeviceCard";
import SearchPanel from "../components/SearchPanel";
import ObjectionsPanel from "../components/ObjectionsPanel";
import CameraSkeleton from "../components/CameraSkeleton";
import { Input } from "../components/ui/Input";
import { useRealtime } from "../hooks/useRealtime";

function StatTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Video;
  label: string;
  value: number | string;
  tone: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface/60 px-4 py-3">
      <div className={`grid h-10 w-10 place-items-center rounded-lg ${tone}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <div className="text-xl font-semibold leading-none text-ink">{value}</div>
        <div className="mt-1 text-xs text-ink-muted">{label}</div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [objectionsOpen, setObjectionsOpen] = useState(false);

  const openCamera = (deviceId: string) => navigate(`/camera/${encodeURIComponent(deviceId)}`);
  const openAt = (deviceId: string, t: number) => {
    setSearchOpen(false);
    setObjectionsOpen(false);
    navigate(`/camera/${encodeURIComponent(deviceId)}?t=${Math.round(t)}`);
  };
  useRealtime(); // мгновенные обновления через WebSocket
  const devicesQuery = useQuery({
    queryKey: ["devices"],
    queryFn: api.devices,
    refetchInterval: 15000, // резервный опрос на случай, если сокет отвалится
  });

  const devices = devicesQuery.data ?? [];
  const onlineCount = devices.filter((d) => d.online).length;

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return devices;
    return devices.filter(
      (d) =>
        d.friendly_name.toLowerCase().includes(term) ||
        d.device_id.toLowerCase().includes(term),
    );
  }, [devices, q]);

  const isInitialLoading = devicesQuery.isLoading;

  return (
    <AppShell
      title="Камеры"
      subtitle={`${devices.length} устройств · ${onlineCount} онлайн`}
      actions={
        <>
          <div className="hidden sm:block sm:w-56">
            <Input
              icon={<Search className="h-[18px] w-[18px]" />}
              placeholder="Поиск камеры…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="h-10"
            />
          </div>
          <button
            onClick={() => setSearchOpen(true)}
            className="hidden h-10 items-center rounded-lg px-3.5 text-sm text-ink-muted ring-1 ring-hairline transition hover:bg-white/5 hover:text-ink sm:inline-flex"
          >
            Поиск по разговорам
          </button>
          <button
            onClick={() => setObjectionsOpen(true)}
            className="hidden h-10 items-center rounded-lg px-3.5 text-sm text-ink-muted ring-1 ring-hairline transition hover:bg-white/5 hover:text-ink sm:inline-flex"
          >
            Возражения
          </button>
          <button
            onClick={() => devicesQuery.refetch()}
            title="Обновить"
            className="grid h-10 w-10 place-items-center rounded-lg text-ink-muted ring-1 ring-hairline transition hover:bg-white/5 hover:text-ink"
          >
            <RefreshCw
              className={`h-[18px] w-[18px] ${devicesQuery.isFetching ? "animate-spin" : ""}`}
            />
          </button>
        </>
      }
    >
      <div className="p-4 sm:p-6">
        {/* KPI */}
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4">
          <StatTile icon={Video} label="Всего камер" value={devices.length} tone="bg-brand/15 text-brand" />
          <StatTile icon={Wifi} label="Онлайн" value={onlineCount} tone="bg-ok/15 text-ok" />
          <StatTile
            icon={WifiOff}
            label="Офлайн"
            value={devices.length - onlineCount}
            tone="bg-white/5 text-ink-faint"
          />
        </div>

        {/* Поиск на мобильных */}
        <div className="mb-4 sm:hidden">
          <Input
            icon={<Search className="h-[18px] w-[18px]" />}
            placeholder="Поиск камеры…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        {/* Сетка */}
        {isInitialLoading ? (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <CameraSkeleton key={i} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-hairline bg-surface/40 px-6 py-20 text-center">
            <div className="mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-white/5">
              <Video className="h-7 w-7 text-ink-faint" />
            </div>
            <h3 className="text-base font-medium text-ink">
              {q ? "Ничего не найдено" : "Пока нет камер"}
            </h3>
            <p className="mt-1 max-w-sm text-sm text-ink-muted">
              {q
                ? "Попробуйте изменить запрос."
                : "Как только устройство пришлёт первый сегмент, оно появится здесь автоматически."}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {filtered.map((d) => (
              <DeviceCard key={d.device_id} device={d} onOpen={(dev) => openCamera(dev.device_id)} />
            ))}
          </div>
        )}
      </div>

      {searchOpen && <SearchPanel onClose={() => setSearchOpen(false)} onPick={openAt} />}
      {objectionsOpen && (
        <ObjectionsPanel onClose={() => setObjectionsOpen(false)} onPick={openAt} />
      )}
    </AppShell>
  );
}
