import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { WifiOff, Clock, Pencil, Check, X, Play, Radio, History } from "lucide-react";
import { api, thumbUrl, Device } from "../api";
import { timeAgo } from "../lib/format";
import { Spinner } from "./ui/Spinner";

export default function DeviceCard({
  device,
  onOpen,
}: {
  device: Device;
  onOpen: (d: Device) => void;
}) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(device.friendly_name);
  const [thumbError, setThumbError] = useState(false);

  const rename = useMutation({
    mutationFn: (n: string) => api.renameDevice(device.device_id, n),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      setEditing(false);
    },
  });

  function save() {
    const trimmed = name.trim();
    if (trimmed && trimmed !== device.friendly_name) rename.mutate(trimmed);
    else setEditing(false);
  }

  const showThumb = !thumbError;

  return (
    <div className="group animate-fade-in overflow-hidden rounded-2xl bg-surface shadow-card ring-1 ring-hairline transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lift hover:ring-brand/30">
      {/* Превью 16:9 — клик открывает просмотрщик (live или архив) */}
      <button
        onClick={() => onOpen(device)}
        className="relative block aspect-video w-full overflow-hidden text-left"
        style={{ background: "radial-gradient(120% 120% at 50% 0%, #16202f 0%, #0c1119 70%)" }}
      >
        {/* Кадр-превью */}
        {showThumb && (
          <img
            src={thumbUrl(device.device_id, device.last_seen)}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            onError={() => setThumbError(true)}
          />
        )}

        {/* Заглушка, если превью ещё нет */}
        {!showThumb && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
            <WifiOff className="h-9 w-9 text-ink-faint/50" strokeWidth={1.5} />
            <span className="text-xs text-ink-faint">
              {device.online ? "Ожидание кадра" : "Нет сигнала"}
            </span>
          </div>
        )}

        {/* Индикатор LIVE / OFFLINE */}
        <div className="absolute left-3 top-3">
          {device.online ? (
            <span className="inline-flex items-center gap-1.5 rounded-md bg-black/60 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-white backdrop-blur">
              <span className="h-1.5 w-1.5 animate-live-blink rounded-full bg-live" />
              Live
            </span>
          ) : (
            <span className="inline-flex items-center rounded-md bg-black/60 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-ink-muted backdrop-blur">
              Offline
            </span>
          )}
        </div>

        {/* Наведение: смотреть (онлайн) или открыть архив (офлайн) */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition group-hover:bg-black/25 group-hover:opacity-100">
          <span className="inline-flex items-center gap-2 rounded-full bg-white/95 px-4 py-2 text-sm font-semibold text-slate-900 shadow-lg">
            {device.online ? (
              <>
                <Play className="h-4 w-4 fill-slate-900" />
                Смотреть
              </>
            ) : (
              <>
                <History className="h-4 w-4" />
                Архив
              </>
            )}
          </span>
        </div>
      </button>

      {/* Подвал: имя + метаданные */}
      <div className="p-4">
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              className="min-w-0 flex-1 rounded-lg bg-black/25 px-2.5 py-1.5 text-sm text-ink ring-1 ring-hairline outline-none focus:ring-2 focus:ring-brand/60"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
              autoFocus
            />
            <button
              onClick={save}
              disabled={rename.isPending}
              className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-white hover:bg-brand-hover disabled:opacity-50"
            >
              {rename.isPending ? <Spinner className="h-4 w-4" /> : <Check className="h-4 w-4" />}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted ring-1 ring-hairline hover:bg-white/5"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${
                device.online ? "bg-ok animate-pulse-ring" : "bg-ink-faint"
              }`}
            />
            <h3
              className="min-w-0 flex-1 truncate text-[15px] font-semibold text-ink"
              title={device.friendly_name}
            >
              {device.friendly_name}
            </h3>
            <button
              onClick={() => {
                setName(device.friendly_name);
                setEditing(true);
              }}
              title="Переименовать"
              className="shrink-0 rounded-md p-1.5 text-ink-faint opacity-0 transition hover:bg-white/5 hover:text-brand group-hover:opacity-100"
            >
              <Pencil className="h-4 w-4" />
            </button>
          </div>
        )}

        <div className="mt-2.5 flex items-center justify-between gap-2 text-[12px] text-ink-muted">
          <span className="inline-flex items-center gap-1.5 font-mono text-ink-faint" title={device.device_id}>
            <Radio className="h-3.5 w-3.5" />
            <span className="max-w-[9rem] truncate">{device.device_id}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5" />
            {timeAgo(device.last_seen)}
          </span>
        </div>
      </div>
    </div>
  );
}
