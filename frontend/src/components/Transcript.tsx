import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "../api";
import { speakerColor } from "../lib/meta";
import { SkeletonLines } from "./ui/Skeleton";

const DAY_MS = 86_400_000;
const fmtClock = (ms: number) =>
  new Date(ms).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

type Line = { id: string; t: number; speaker: string; text: string };

// В эфире «сейчас» тикает внутри транскрипта (раз в 2 с — этого хватает для
// подсветки активной реплики), чтобы не перерисовывать всю страницу каждую секунду.
function useLiveNow(active: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 2000);
    return () => window.clearInterval(id);
  }, [active]);
  return active ? now : null;
}

function Transcript({
  deviceId,
  dayStart,
  position,
  live = false,
  onSeek,
}: {
  deviceId: string;
  dayStart: number;
  position: number | null;
  live?: boolean;
  onSeek: (ms: number) => void;
}) {
  const [q, setQ] = useState("");
  const fromISO = new Date(dayStart).toISOString();
  const toISO = new Date(dayStart + DAY_MS).toISOString();
  const isToday = dayStart === new Date(new Date().setHours(0, 0, 0, 0)).getTime();

  const liveNow = useLiveNow(live);
  const playhead = live ? liveNow : position;

  const query = useQuery({
    queryKey: ["transcript", deviceId, dayStart],
    queryFn: () => api.transcript(deviceId, fromISO, toISO),
    refetchInterval: isToday ? 15000 : false,
  });
  const raw = query.data ?? [];

  // Только распознанная речь. Реплики, переписанные моделью, сюда не попадают:
  // у них выдуманные таймкоды — клик уводил мимо на десятки секунд, а порядок
  // строк ломался. Разбор эпизодов живёт в «Сводке», здесь — что реально сказано.
  const lines: Line[] = useMemo(
    () =>
      raw
        .map((l) => ({ id: `r${l.id}-${l.start}`, t: l.start, speaker: "", text: l.text }))
        .sort((a, b) => a.t - b.t),
    [raw],
  );

  // Здоровье распознавания — индикатор в шапке.
  const statusQuery = useQuery({
    queryKey: ["transcribeStatus"],
    queryFn: () => api.transcribeStatus(),
    refetchInterval: 30000,
  });
  const stt = statusQuery.data;
  let dotColor = "#6b7280";
  let dotTip = "Распознавание выключено (нет ключа Deepgram)";
  if (stt?.enabled) {
    const failing = !!stt.last_error_at && (!stt.last_ok_at || stt.last_error_at > stt.last_ok_at);
    const tail = `Успешно: ${stt.ok}, ошибок: ${stt.failed}, повторов: ${stt.retries}`;
    dotColor = failing ? "#f59e0b" : "#22c55e";
    dotTip = failing
      ? `Проблема с распознаванием: ${stt.last_error ?? "ошибка"}. ${tail}`
      : `Распознавание работает (${stt.model}). ${tail}`;
  }

  const needle = q.trim().toLowerCase();
  const filtered = useMemo(
    () => (needle ? lines.filter((l) => l.text.toLowerCase().includes(needle)) : lines),
    [lines, needle],
  );

  // Активная реплика — с наибольшим временем, не превышающим позицию плеера.
  const activeId = useMemo(() => {
    if (playhead === null) return null;
    let hit: Line | null = null;
    for (const l of lines) {
      if (l.t <= playhead) hit = l;
      else break;
    }
    return hit?.id ?? null;
  }, [lines, playhead]);

  const activeRef = useRef<HTMLButtonElement>(null);
  const pauseUntil = useRef(0);
  const pause = () => {
    pauseUntil.current = Date.now() + 4000;
  };
  useEffect(() => {
    if (Date.now() < pauseUntil.current) return;
    activeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeId]);

  const items = useMemo(
    () =>
      filtered.map((l) => {
        const active = l.id === activeId;
        const sc = speakerColor(l.speaker);
        return (
          <button
            key={l.id}
            ref={active ? activeRef : undefined}
            onClick={() => onSeek(l.t)}
            className={`flex w-full gap-2.5 rounded-md px-2 py-1.5 text-left transition ${
              active ? "bg-brand/15 ring-1 ring-brand/30" : "hover:bg-white/5"
            }`}
          >
            <span className="shrink-0 pt-0.5 font-mono text-[12px] tabular-nums text-ink-faint">
              {fmtClock(l.t)}
            </span>
            <span className={`text-[14px] leading-snug ${active ? "text-ink" : "text-ink-muted"}`}>
              {l.speaker && (
                <span className="mr-1 font-medium" style={{ color: sc || undefined }}>
                  {l.speaker}:
                </span>
              )}
              {l.text}
            </span>
          </button>
        );
      }),
    [filtered, activeId, onSeek],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-hairline px-1 pb-2">
        <span className="text-[14px] font-medium text-ink">Транскрипт</span>
        <span
          className="h-2 w-2 shrink-0 cursor-help rounded-full"
          style={{ background: dotColor }}
          title={dotTip}
        />
        <div className="relative ml-auto">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск по тексту…"
            className="w-40 rounded-md border border-hairline bg-black/30 py-1 pl-7 pr-2 text-[13px] text-ink outline-none transition focus:border-brand"
          />
        </div>
      </div>

      <div
        onWheel={pause}
        onPointerDown={pause}
        onTouchStart={pause}
        className="min-h-0 flex-1 overflow-y-auto py-1.5"
      >
        {query.isLoading ? (
          <SkeletonLines rows={9} />
        ) : filtered.length === 0 ? (
          <p className="px-2 py-3 text-center text-[13px] text-ink-faint">
            {needle ? "Ничего не найдено." : "Речь за этот день не распознана."}
          </p>
        ) : (
          items
        )}
      </div>
    </div>
  );
}

export default memo(Transcript);
