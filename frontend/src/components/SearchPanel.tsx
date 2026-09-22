import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { api } from "../api";
import { TYPE_META } from "../lib/meta";
import { SkeletonCards } from "./ui/Skeleton";

const fmtWhen = (ms: number) =>
  new Date(ms).toLocaleString("ru-RU", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });

export default function SearchPanel({
  onClose,
  onPick,
}: {
  onClose: () => void;
  onPick: (deviceId: string, start: number) => void;
}) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const q = query.trim();
  const search = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.search(q, 30),
    enabled: q.length >= 2,
  });
  const results = search.data?.results ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/80 p-4 pt-16 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-surface shadow-lift ring-1 ring-hairline"
        onClick={(e) => e.stopPropagation()}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setQuery(text);
          }}
          className="flex items-center gap-2 border-b border-hairline px-4 py-3"
        >
          <Search className="h-5 w-5 shrink-0 text-ink-faint" />
          <input
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Поиск по разговорам…"
            className="w-full bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-faint"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-muted transition hover:bg-white/5 hover:text-ink"
          >
            <X className="h-5 w-5" />
          </button>
        </form>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {q.length < 2 ? (
            <p className="px-2 py-8 text-center text-[13px] text-ink-faint">
              Введите запрос — ищем по смыслу во всех разобранных разговорах.
            </p>
          ) : search.isLoading ? (
            <SkeletonCards count={5} />
          ) : results.length === 0 ? (
            <p className="px-2 py-8 text-center text-[13px] text-ink-faint">
              Ничего не нашлось. Возможно, разговоры ещё не разобраны AI.
            </p>
          ) : (
            <div className="space-y-1.5">
              {results.map((r) => {
                const meta = TYPE_META[r.type] ?? TYPE_META.other;
                return (
                  <button
                    key={r.id}
                    onClick={() => onPick(r.device_id, r.start)}
                    className="w-full rounded-lg border border-hairline bg-black/20 p-2.5 text-left transition hover:bg-white/5"
                  >
                    <div className="mb-1 flex items-center gap-2">
                      <span
                        className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white"
                        style={{ background: meta.color }}
                      >
                        {meta.label}
                      </span>
                      <span className="text-[13px] font-medium text-ink">{r.device_name}</span>
                      <span className="font-mono text-[12px] tabular-nums text-ink-faint">
                        {fmtWhen(r.start)}
                      </span>
                      {r.score !== null && (
                        <span className="text-[12px] text-ink-muted">оценка {r.score}</span>
                      )}
                      <span className="ml-auto text-[11px] text-ink-faint">
                        {Math.round(r.similarity * 100)}%
                      </span>
                    </div>
                    {r.title && <p className="text-[13px] font-medium text-ink">{r.title}</p>}
                    {r.summary && (
                      <p className="line-clamp-2 text-[13px] leading-snug text-ink-muted">{r.summary}</p>
                    )}
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
