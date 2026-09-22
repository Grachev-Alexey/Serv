import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../api";
import { KIND_META } from "../lib/meta";
import { SkeletonCards } from "./ui/Skeleton";

const fmtWhen = (ms: number) =>
  new Date(ms).toLocaleString("ru-RU", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });

export default function ObjectionsPanel({
  onClose,
  onPick,
}: {
  onClose: () => void;
  onPick: (deviceId: string, t: number) => void;
}) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<string>("all");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const query = useQuery({ queryKey: ["objections"], queryFn: () => api.objections(300) });
  const all = query.data?.items ?? [];

  const needle = q.trim().toLowerCase();
  const items = useMemo(
    () =>
      all.filter(
        (o) =>
          (kind === "all" || o.kind === kind) &&
          (!needle || o.text.toLowerCase().includes(needle)),
      ),
    [all, kind, needle],
  );

  const kinds = ["all", "objection", "contra", "complaint", "redflag"];

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/80 p-4 pt-16 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-surface shadow-lift ring-1 ring-hairline"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-hairline px-4 py-3">
          <span className="text-[15px] font-medium text-ink">Библиотека возражений</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Фильтр по тексту…"
            className="ml-3 w-48 rounded-md border border-hairline bg-black/30 px-2.5 py-1 text-[13px] text-ink outline-none transition focus:border-brand"
          />
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="ml-auto grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-muted transition hover:bg-white/5 hover:text-ink"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5 border-b border-hairline px-4 py-2">
          {kinds.map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`rounded-md px-2.5 py-1 text-[12px] transition ${
                kind === k ? "bg-brand text-white" : "text-ink-muted ring-1 ring-hairline hover:bg-white/5"
              }`}
            >
              {k === "all" ? "Все" : KIND_META[k]?.label ?? k}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {query.isLoading ? (
            <SkeletonCards count={5} />
          ) : items.length === 0 ? (
            <p className="px-2 py-8 text-center text-[13px] text-ink-faint">
              Пока ничего нет. Возражения появятся, когда AI разберёт разговоры.
            </p>
          ) : (
            <div className="space-y-1.5">
              {items.map((o, i) => {
                const meta = KIND_META[o.kind] ?? { label: o.kind, color: "#6b7280" };
                return (
                  <button
                    key={i}
                    onClick={() => onPick(o.device_id, o.t)}
                    className="w-full rounded-lg border border-hairline bg-black/20 p-2.5 text-left transition hover:bg-white/5"
                  >
                    <div className="mb-1 flex items-center gap-2">
                      <span
                        className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white"
                        style={{ background: meta.color }}
                      >
                        {meta.label}
                      </span>
                      <span className="text-[13px] font-medium text-ink">{o.device_name}</span>
                      <span className="font-mono text-[12px] tabular-nums text-ink-faint">{fmtWhen(o.t)}</span>
                      {o.score !== null && (
                        <span className="ml-auto text-[12px] text-ink-muted">оценка {o.score}</span>
                      )}
                    </div>
                    <p className="text-[14px] leading-snug text-ink">{o.text}</p>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
