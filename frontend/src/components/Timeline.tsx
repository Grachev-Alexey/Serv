import { memo, useEffect, useRef, useState } from "react";
import { ZoomIn, ZoomOut } from "lucide-react";
import { TimeRange, EventRange, frameUrl } from "../api";
import { EP_GRADIENT, EP_SWATCH, IDLE_SWATCH, EVENT_SWATCH, kindColor } from "../lib/meta";

const DAY_MS = 86_400_000;
const MIN_SPAN = 30_000;

const STEPS = [
  30_000, 60_000, 300_000, 600_000, 900_000, 1_800_000,
  3_600_000, 7_200_000, 10_800_000, 21_600_000, 43_200_000,
];

function pickStep(span: number): number {
  const target = span / 9;
  return STEPS.find((s) => s >= target) ?? STEPS[STEPS.length - 1];
}

function fmtTick(ms: number, withSeconds: boolean): string {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  if (withSeconds) return `${hh}:${mm}:${String(d.getSeconds()).padStart(2, "0")}`;
  return `${hh}:${mm}`;
}

const fmtFull = (ms: number) => new Date(ms).toLocaleTimeString("ru-RU");

type Episode = { start: number; end: number; type: string };
type Pin = { t: number; kind: string };
type View = { start: number; end: number };

// Красная вертикаль текущей позиции + треугольный маркер. Презентационный —
// используется и для архивной позиции, и для «живого» плейхеда.
function PlayheadMarker({ leftPct }: { leftPct: number }) {
  return (
    <div
      className="absolute top-0 z-20 h-full"
      style={{
        left: `${leftPct}%`, width: "2px", marginLeft: "-1px",
        background: "#ff2d2d", boxShadow: "0 0 8px 1px rgba(255,45,45,0.95)",
      }}
    >
      <div
        style={{
          position: "absolute", top: "-1px", left: "1px", transform: "translateX(-50%)",
          width: 0, height: 0, borderLeft: "5px solid transparent",
          borderRight: "5px solid transparent", borderTop: "8px solid #ff2d2d",
        }}
      />
    </div>
  );
}

// В эфире «сейчас» едет каждую секунду. Держим этот тик ЗДЕСЬ, в крошечном
// компоненте, чтобы ежесекундно перерисовывалась только красная вертикаль, а не
// вся полоса (сотни div'ов записи/эпизодов/делений).
function LivePlayhead({ view }: { view: View }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  if (now < view.start || now > view.end) return null;
  return <PlayheadMarker leftPct={((now - view.start) / (view.end - view.start)) * 100} />;
}

function Timeline({
  deviceId,
  dayStart,
  ranges,
  events,
  idle = [],
  episodes = [],
  pins = [],
  position,
  live = false,
  onSeek,
  onViewChange,
}: {
  deviceId: string;
  dayStart: number;
  ranges: TimeRange[];
  events: EventRange[];
  idle?: TimeRange[];
  episodes?: Episode[];
  pins?: Pin[];
  position: number | null;
  live?: boolean;
  onSeek: (ms: number) => void;
  onViewChange?: (start: number, end: number) => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>({ start: dayStart, end: dayStart + DAY_MS });

  const onViewChangeRef = useRef(onViewChange);
  onViewChangeRef.current = onViewChange;
  useEffect(() => {
    onViewChangeRef.current?.(view.start, view.end);
  }, [view.start, view.end]);
  const [hover, setHover] = useState<{ ms: number; x: number } | null>(null);
  const [broken, setBroken] = useState<number | null>(null);
  const fittedRef = useRef<number | null>(null);
  const drag = useRef<{ x: number; start: number; end: number; moved: boolean } | null>(null);

  const span = view.end - view.start;
  const pct = (ms: number) => ((ms - view.start) / span) * 100;

  const clampView = (start: number, end: number) => {
    const s = end - start;
    if (start < dayStart) return { start: dayStart, end: dayStart + s };
    if (end > dayStart + DAY_MS) return { start: dayStart + DAY_MS - s, end: dayStart + DAY_MS };
    return { start, end };
  };

  const allBlocks = [...ranges, ...events, ...idle];   // для наведения/превью — по любому участку
  const activeBlocks = [...ranges, ...events];          // «К записям» фокусируем на активности, не на простое

  const fitToRanges = () => {
    const src = activeBlocks.length ? activeBlocks : allBlocks;
    if (!src.length) return setView({ start: dayStart, end: dayStart + DAY_MS });
    const lo = Math.min(...src.map((r) => r.start));
    const hi = Math.max(...src.map((r) => r.end));
    const pad = Math.max(60_000, (hi - lo) * 0.15);
    const start = Math.max(dayStart, lo - pad);
    const end = Math.min(dayStart + DAY_MS, hi + pad);
    setView(clampView(start, Math.max(end, start + MIN_SPAN)));
  };

  useEffect(() => {
    setView({ start: dayStart, end: dayStart + DAY_MS });
    fittedRef.current = null;
  }, [dayStart]);

  useEffect(() => {
    if (allBlocks.length && fittedRef.current !== dayStart) {
      fitToRanges();
      fittedRef.current = dayStart;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ranges, events, dayStart]);

  useEffect(() => {
    const bar = barRef.current;
    if (!bar) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = bar.getBoundingClientRect();
      const frac = (e.clientX - rect.left) / rect.width;
      setView((v) => {
        const sp = v.end - v.start;
        const cursor = v.start + frac * sp;
        const factor = e.deltaY < 0 ? 0.8 : 1.25;
        const newSpan = Math.min(DAY_MS, Math.max(MIN_SPAN, sp * factor));
        return clampView(cursor - frac * newSpan, cursor - frac * newSpan + newSpan);
      });
    };
    bar.addEventListener("wheel", onWheel, { passive: false });
    return () => bar.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dayStart]);

  const zoom = (factor: number) => {
    setView((v) => {
      const sp = v.end - v.start;
      const mid = v.start + sp / 2;
      const newSpan = Math.min(DAY_MS, Math.max(MIN_SPAN, sp * factor));
      return clampView(mid - newSpan / 2, mid + newSpan / 2);
    });
  };

  function onPointerDown(e: React.PointerEvent) {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, start: view.start, end: view.end, moved: false };
  }
  function onPointerMove(e: React.PointerEvent) {
    const bar = barRef.current;
    if (!bar) return;
    const d = drag.current;
    if (d) {
      const dx = e.clientX - d.x;
      if (Math.abs(dx) > 3) d.moved = true;
      if (d.moved) {
        const shift = (dx / bar.clientWidth) * (d.end - d.start);
        setView(clampView(d.start - shift, d.end - shift));
        setHover(null);
        return;
      }
    }
    const rect = bar.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    setHover({ ms: view.start + frac * span, x: e.clientX - rect.left });
  }
  function onPointerUp(e: React.PointerEvent) {
    const d = drag.current;
    const bar = barRef.current;
    drag.current = null;
    if (!d || !bar) return;
    if (!d.moved) {
      const rect = bar.getBoundingClientRect();
      const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      onSeek(view.start + frac * span);
    }
  }

  // Клик по дорожке аналитики — та же ось времени, перематывает к моменту эпизода.
  function laneSeek(e: React.MouseEvent) {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(view.start + frac * span);
  }

  const step = pickStep(span);
  const withSeconds = step < 60_000;
  const firstTick = dayStart + Math.ceil((view.start - dayStart) / step) * step;
  const ticks: number[] = [];
  for (let t = firstTick; t <= view.end; t += step) ticks.push(t);

  // Превью показываем только над записанным участком
  const hoveredHasRec = hover
    ? allBlocks.some((r) => hover.ms >= r.start && hover.ms <= r.end)
    : false;
  const bucket = hover ? Math.floor(hover.ms / 5000) * 5000 : 0;
  const barW = barRef.current?.clientWidth ?? 0;
  const previewLeft = hover ? Math.min(Math.max(hover.x, 92), Math.max(92, barW - 92)) : 0;

  // Превью-кадр грузим только когда курсор «замер» (~130 мс), а не на каждом
  // пройденном 5-сек. бакете — иначе быстрый свайп по таймлайну устраивает
  // шторм запросов /frame к бэкенду (каждый — запрос к БД) и подвешивает API.
  const [previewBucket, setPreviewBucket] = useState<number | null>(null);
  useEffect(() => {
    if (!hover || !hoveredHasRec) return;
    const b = bucket;
    const id = window.setTimeout(() => setPreviewBucket(b), 130);
    return () => window.clearTimeout(id);
  }, [bucket, hover, hoveredHasRec]);

  const analyticEpisodes = episodes.filter(
    (e) => EP_GRADIENT[e.type] && e.end >= view.start && e.start <= view.end,
  );

  return (
    <div className="relative select-none">
      {/* Панель управления масштабом + легенда */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {episodes.some((e) => e.type === "consultation" || e.type === "sale") && (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-faint">
              <span className="h-2 w-2 rounded-sm" style={{ background: EP_SWATCH.consultation }} /> консультация
            </span>
          )}
          {episodes.some((e) => e.type === "distraction") && (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-faint">
              <span className="h-2 w-2 rounded-sm" style={{ background: EP_SWATCH.distraction }} /> отвлечение
            </span>
          )}
          {idle.length > 0 && (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-faint">
              <span className="h-2 w-2 rounded-sm" style={{ background: IDLE_SWATCH }} /> простой
            </span>
          )}
          {events.length > 0 && (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-faint">
              <span className="h-2 w-2 rounded-sm" style={{ background: EVENT_SWATCH }} /> зум-запись
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => zoom(0.5)} title="Приблизить" className="grid h-7 w-7 place-items-center rounded-md text-ink-muted ring-1 ring-hairline hover:bg-white/5 hover:text-ink">
            <ZoomIn className="h-4 w-4" />
          </button>
          <button onClick={() => zoom(2)} title="Отдалить" className="grid h-7 w-7 place-items-center rounded-md text-ink-muted ring-1 ring-hairline hover:bg-white/5 hover:text-ink">
            <ZoomOut className="h-4 w-4" />
          </button>
          <button onClick={fitToRanges} className="h-7 rounded-md px-2.5 text-[12px] text-ink-muted ring-1 ring-hairline hover:bg-white/5 hover:text-ink">
            К записям
          </button>
          <button onClick={() => setView({ start: dayStart, end: dayStart + DAY_MS })} className="h-7 rounded-md px-2.5 text-[12px] text-ink-muted ring-1 ring-hairline hover:bg-white/5 hover:text-ink">
            Сутки
          </button>
        </div>
      </div>

      {/* Всплывающее превью */}
      {hover && hoveredHasRec && (
        <div className="pointer-events-none absolute z-50 -translate-x-1/2" style={{ left: previewLeft, bottom: "calc(100% - 26px)" }}>
          <div className="overflow-hidden rounded-lg border border-hairline bg-black shadow-lift">
            {previewBucket === null ? (
              <div className="h-[101px] w-[180px] animate-pulse bg-white/5" />
            ) : broken === previewBucket ? (
              <div className="grid h-[101px] w-[180px] place-items-center text-[11px] text-ink-faint">нет кадра</div>
            ) : (
              <img
                key={previewBucket}
                src={frameUrl(deviceId, previewBucket)}
                alt=""
                className="block h-[101px] w-[180px] object-cover"
                onError={() => setBroken(previewBucket)}
              />
            )}
            <div className="px-2 py-1 text-center text-[11px] tabular-nums text-ink">{fmtFull(hover.ms)}</div>
          </div>
        </div>
      )}

      {/* Главная полоса: что записано (запись / простой / зум) + пины + плейхед */}
      <div
        ref={barRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setHover(null)}
        className="relative h-16 cursor-crosshair touch-none rounded-lg bg-black/30 ring-1 ring-hairline"
      >
        {/* Слой визуала (обрезается по краям полосы) */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-lg">
          {ticks.map((t) => (
            <div key={t} className="absolute top-0 h-full border-l border-white/[0.06]" style={{ left: `${pct(t)}%` }} />
          ))}

          {/* Простой (idle): камера писала, но картинка не менялась — серым, приглушённо */}
          {idle
            .filter((r) => r.end >= view.start && r.start <= view.end)
            .map((r, i) => {
              const left = pct(Math.max(r.start, view.start));
              const width = pct(Math.min(r.end, view.end)) - left;
              return (
                <div
                  key={`i${i}`}
                  className="absolute rounded-[2px]"
                  style={{
                    left: `${left}%`, width: `${width}%`, minWidth: "2px", top: "12px", bottom: "24px",
                    background: "linear-gradient(180deg, #3a4358 0%, #2a3140 100%)",
                    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.05)",
                  }}
                />
              );
            })}

          {/* Обычная запись (синие блоки) */}
          {ranges
            .filter((r) => r.end >= view.start && r.start <= view.end)
            .map((r, i) => {
              const left = pct(Math.max(r.start, view.start));
              const width = pct(Math.min(r.end, view.end)) - left;
              return (
                <div
                  key={`r${i}`}
                  className="absolute rounded-[3px]"
                  style={{
                    left: `${left}%`, width: `${width}%`, minWidth: "3px", top: "6px", bottom: "22px",
                    background: "linear-gradient(180deg, #5b9bff 0%, #2f6bd8 100%)",
                    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.18), 0 1px 4px rgba(0,0,0,0.4)",
                  }}
                />
              );
            })}

          {/* Спец-записи (zoom-записи): янтарные блоки */}
          {events
            .filter((r) => r.end >= view.start && r.start <= view.end)
            .map((r, i) => {
              const left = pct(Math.max(r.start, view.start));
              const width = pct(Math.min(r.end, view.end)) - left;
              return (
                <div
                  key={`e${i}`}
                  className="absolute rounded-[3px]"
                  style={{
                    left: `${left}%`, width: `${width}%`, minWidth: "4px", top: "6px", bottom: "22px",
                    background: "linear-gradient(180deg, #fbbf24 0%, #d97706 100%)",
                    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.25), 0 1px 4px rgba(0,0,0,0.4)",
                  }}
                />
              );
            })}

          {/* Пины ключевых моментов (визуальные метки; клик по полосе перематывает рядом) */}
          {pins
            .filter((p) => p.t >= view.start && p.t <= view.end)
            .map((p, i) => (
              <div
                key={`pin${i}`}
                className="absolute top-0 z-10 h-2.5 w-[3px] -translate-x-1/2 rounded-b"
                style={{ left: `${pct(p.t)}%`, background: kindColor(p.kind) }}
              />
            ))}

          {/* Ползунок текущей позиции: в эфире — свой тик, в архиве — позиция плеера */}
          {live ? (
            <LivePlayhead view={view} />
          ) : (
            position !== null && position >= view.start && position <= view.end && (
              <PlayheadMarker leftPct={pct(position)} />
            )
          )}
        </div>

        {/* Подписи делений (поверх, снизу; у краёв прижимаем внутрь) */}
        {ticks.map((t) => {
          const p = pct(t);
          const edgeLeft = p <= 4;
          const edgeRight = p >= 96;
          const cls = edgeLeft ? "translate-x-0" : edgeRight ? "-translate-x-full" : "-translate-x-1/2";
          const left = edgeLeft ? "3px" : edgeRight ? "calc(100% - 3px)" : `${p}%`;
          return (
            <span
              key={`l${t}`}
              className={`pointer-events-none absolute bottom-0.5 text-[10px] tabular-nums text-ink-faint ${cls}`}
              style={{ left }}
            >
              {fmtTick(t, withSeconds)}
            </span>
          );
        })}
      </div>

      {/* Дорожка аналитики: AI-эпизоды отдельной полосой под записью (не поверх) */}
      {analyticEpisodes.length > 0 && (
        <div
          onClick={laneSeek}
          title="AI-разбор: консультации, продажи, отвлечения"
          className="relative mt-1.5 h-3.5 cursor-pointer overflow-hidden rounded bg-black/25 ring-1 ring-hairline"
        >
          {analyticEpisodes.map((e, i) => {
            const left = pct(Math.max(e.start, view.start));
            const width = pct(Math.min(e.end, view.end)) - left;
            return (
              <div
                key={`ep${i}`}
                className="absolute inset-y-0"
                style={{
                  left: `${left}%`, width: `${width}%`, minWidth: "2px",
                  background: EP_GRADIENT[e.type],
                  boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.14)",
                }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

export default memo(Timeline);
