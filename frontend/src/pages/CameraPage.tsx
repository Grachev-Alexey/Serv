import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, Radio, ChevronLeft, ChevronRight, History, Download, Trash2,
} from "lucide-react";
import { api, liveUrl, archiveUrl, exportUrl } from "../api";
import AppShell from "../components/AppShell";
import HlsVideo from "../components/HlsVideo";
import Timeline from "../components/Timeline";
import Transcript from "../components/Transcript";
import Conversations from "../components/Conversations";
import { useRealtime } from "../hooks/useRealtime";

const DAY_MS = 86_400_000;

const startOfLocalDay = (d: Date) => {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x.getTime();
};
const fmtDate = (ms: number) =>
  new Date(ms).toLocaleDateString("ru-RU", { day: "2-digit", month: "long", year: "numeric" });
const fmtClock = (ms: number) => new Date(ms).toLocaleTimeString("ru-RU");

const pad2 = (n: number) => String(n).padStart(2, "0");
const msToTime = (ms: number) => {
  const d = new Date(ms);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};
const timeToMs = (day: number, t: string) => {
  const [h, m] = t.split(":").map(Number);
  return day + ((h || 0) * 60 + (m || 0)) * 60_000;
};

// Живые часы в шапке архива/эфира — отдельный компонент с собственным тиком,
// чтобы ежесекундное обновление времени не дёргало всю страницу.
function LiveClock() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return <>{fmtClock(now)}</>;
}

export default function CameraPage() {
  const { deviceId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  useRealtime(); // мгновенные обновления через WebSocket

  // Момент из ссылки (?t=) — из поиска/возражений/дип-линка.
  const initialTime = useMemo(() => {
    const t = Number(searchParams.get("t"));
    return Number.isFinite(t) && t > 0 ? t : null;
  }, [searchParams]);

  const devicesQuery = useQuery({
    queryKey: ["devices"],
    queryFn: api.devices,
    refetchInterval: 15000,
  });
  const devicesLoaded = !!devicesQuery.data;
  const device = devicesQuery.data?.find((d) => d.device_id === deviceId) ?? null;
  const deviceName = device?.friendly_name ?? deviceId;
  const online = device?.online ?? false;
  const views = device?.views ?? 1;

  const [dayStart, setDayStart] = useState(() =>
    startOfLocalDay(initialTime ? new Date(initialTime) : new Date()),
  );
  const [mode, setMode] = useState<"live" | "archive">(initialTime ? "archive" : "live");
  const [archiveFrom, setArchiveFrom] = useState<number | null>(initialTime ?? null);
  const [archiveTo, setArchiveTo] = useState<number | null>(
    initialTime ? initialTime + 10 * 60_000 : null,
  );
  const [position, setPosition] = useState<number | null>(initialTime ?? null);
  const [view, setView] = useState(0);
  const [dlOpen, setDlOpen] = useState(false);
  const [dlFrom, setDlFrom] = useState("00:00");
  const [dlTo, setDlTo] = useState("23:59");
  const [viewRange, setViewRange] = useState({ start: dayStart, end: dayStart + DAY_MS });
  const [rightTab, setRightTab] = useState<"transcript" | "summary">("transcript");
  const [seekMiss, setSeekMiss] = useState(false); // кликнули по моменту, где видео уже удалено

  // Если камера офлайн и мы ещё не трогали режим — открываем архив, а не пустой эфир.
  const touchedMode = useRef(!!initialTime);
  useEffect(() => {
    if (!touchedMode.current && device && !device.online && mode === "live") {
      setMode("archive");
    }
  }, [device, mode]);

  const playhead = mode === "live" ? null : position; // «живой» плейхед таймлайн/транскрипт рисуют сами

  const fromISO = new Date(dayStart).toISOString();
  const toISO = new Date(dayStart + DAY_MS).toISOString();
  const isToday = dayStart === startOfLocalDay(new Date());
  const isPast = dayStart < startOfLocalDay(new Date());

  const timelineQuery = useQuery({
    queryKey: ["timeline", deviceId, dayStart],
    queryFn: () => api.timeline(deviceId, fromISO, toISO),
    refetchInterval: isToday ? 15000 : false,
  });
  const ranges = timelineQuery.data?.ranges ?? [];
  const events = timelineQuery.data?.events ?? [];
  const idle = timelineQuery.data?.idle ?? [];
  const blocks = [...ranges, ...events, ...idle]; // запись, спец-события и простой — все перематываемы

  // AI-разборы за день — нужны и таймлайну (раскраска + пины), и обеим панелям.
  const convQuery = useQuery({
    queryKey: ["conversations", deviceId, dayStart],
    queryFn: () => api.conversations(deviceId, fromISO, toISO),
    refetchInterval: isToday ? 30000 : false,
  });
  const conversations = useMemo(() => convQuery.data ?? [], [convQuery.data]);
  // Тихое отвлечение (зрение по кадрам) — приходит с таймлайном; на дорожке аналитики
  // показываем теми же оранжевыми полосами, что и отвлечение из речи.
  const distractions = useMemo(() => timelineQuery.data?.distractions ?? [], [timelineQuery.data]);
  const episodes = useMemo(
    () => [
      ...conversations.map((c) => ({ start: c.start, end: c.end, type: c.type as string })),
      ...distractions.map((d) => ({ start: d.start, end: d.end, type: "distraction" })),
    ],
    [conversations, distractions],
  );
  const pins = useMemo(
    () => conversations.flatMap((c) => c.highlights.map((h) => ({ t: h.t, kind: h.kind }))),
    [conversations],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && navigate("/");
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  const seekTo = useCallback(
    (t: number) => {
      touchedMode.current = true;
      // Играем в пределах непрерывного участка (запись или спец-событие).
      let block = blocks.find((r) => t >= r.start && t < r.end);
      let target = t;
      if (!block) {
        block = blocks.filter((r) => r.start > t).sort((a, b) => a.start - b.start)[0];
        target = block ? block.start : t;
      }
      if (!block) {
        setSeekMiss(true); // на этом участке видео нет/уже удалено
        setMode("archive");
        setArchiveFrom(null);
        setPosition(null);
        return;
      }
      setSeekMiss(false);
      setMode("archive");
      setArchiveFrom(target);
      setArchiveTo(block.end);
      setPosition(target);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ranges, events, idle],
  );

  // Перемотка по клику на реплику/пин — устойчивая: с допуском на стыки и короткие
  // сегменты, а если точного блока нет (видео уже удалено ретеншеном) — показываем
  // состояние «видео удалено», но транскрипт/разбор остаются.
  const seekToTranscript = useCallback(
    (t: number) => {
      touchedMode.current = true;
      if (!blocks.length) {
        setSeekMiss(true);
        setMode("archive");
        setArchiveFrom(null);
        setPosition(null);
        return;
      }
      const TOL = 2500; // мс допуска на стыки/подрезку/округление
      let block = blocks.find((r) => t >= r.start - TOL && t <= r.end + TOL);
      let from = t;
      if (!block) {
        block = [...blocks].sort((a, b) => Math.abs(a.start - t) - Math.abs(b.start - t))[0];
        from = block.start; // точного видео нет — играем ближайшую запись с начала
      }
      from = Math.max(block.start, Math.min(from, block.end - 1));
      setSeekMiss(false);
      setMode("archive");
      setArchiveFrom(from);
      setArchiveTo(block.end);
      setPosition(from);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ranges, events, idle],
  );

  const goLive = () => {
    touchedMode.current = true;
    setDayStart(startOfLocalDay(new Date()));
    setArchiveFrom(null);
    setArchiveTo(null);
    setPosition(null);
    setSeekMiss(false);
    setMode("live");
  };

  const changeDay = (deltaDays: number) => {
    touchedMode.current = true;
    setDayStart((d) => d + deltaDays * DAY_MS);
    setArchiveFrom(null);
    setArchiveTo(null);
    setPosition(null);
    setSeekMiss(false);
    setMode("archive");
  };

  const onTime = useCallback(
    (sec: number, wall?: number) => {
      // wall — время съёмки из плейлиста (EXT-X-PROGRAM-DATE-TIME). Если оно
      // есть, берём его: арифметика от archiveFrom врёт, потому что плейлист
      // начинается с головы сегмента и рвётся на дырах архива.
      if (mode !== "archive") return;
      if (wall) setPosition(wall);
      else if (archiveFrom !== null) setPosition(archiveFrom + sec * 1000);
    },
    [mode, archiveFrom],
  );

  // Открывая меню, подставляем текущий видимый участок таймлайна как отправную точку.
  function openDownload() {
    const start = Math.min(Math.max(viewRange.start, dayStart), dayStart + DAY_MS - 60_000);
    const end = viewRange.end >= dayStart + DAY_MS ? dayStart + DAY_MS - 60_000 : viewRange.end;
    setDlFrom(msToTime(start));
    setDlTo(msToTime(end));
    setDlOpen(true);
  }

  function quickFill(minutes: number) {
    const end = isToday ? Math.min(Date.now(), dayStart + DAY_MS - 60_000) : dayStart + DAY_MS - 60_000;
    const start = Math.max(dayStart, end - minutes * 60_000);
    setDlFrom(msToTime(start));
    setDlTo(msToTime(end));
  }

  const dlFromMs = timeToMs(dayStart, dlFrom);
  const dlToMs = timeToMs(dayStart, dlTo);
  const dlValid = dlToMs > dlFromMs;

  function download() {
    if (!dlValid) return;
    const a = document.createElement("a");
    a.href = exportUrl(deviceId, new Date(dlFromMs).toISOString(), new Date(dlToMs).toISOString(), view);
    document.body.appendChild(a);
    a.click();
    a.remove();
    setDlOpen(false);
  }

  const hasVideo = blocks.length > 0;
  const hadActivity = conversations.length > 0;
  // Показать «видео удалено», когда: явный промах по удалённому моменту, ЛИБО за
  // прошедший день видео нет, но была активность (значит его убрал ретеншен).
  const videoGone = seekMiss || (!hasVideo && isPast && hadActivity);

  const notFound = !devicesQuery.isLoading && devicesQuery.data && !device;

  return (
    <AppShell
      title={notFound ? "Камера не найдена" : deviceName}
      subtitle={
        notFound ? undefined : (
          <span className="inline-flex items-center gap-1.5">
            <Radio className="h-3 w-3" />
            <span className="font-mono">{deviceId}</span>
            {devicesLoaded &&
              (online ? (
                <span className="text-ok">· онлайн</span>
              ) : (
                <span className="text-ink-faint">· офлайн</span>
              ))}
          </span>
        )
      }
      leading={
        <button
          onClick={() => navigate("/")}
          title="К камерам"
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-ink-muted ring-1 ring-hairline transition hover:bg-white/5 hover:text-ink"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
      }
      actions={
        notFound ? undefined : (
          <button
            onClick={goLive}
            disabled={!online}
            className={`inline-flex h-10 items-center gap-2 rounded-lg px-3.5 text-sm font-medium transition disabled:opacity-40 ${
              mode === "live"
                ? "bg-live/15 text-live ring-1 ring-live/30"
                : "text-ink-muted ring-1 ring-hairline hover:bg-white/5 hover:text-ink"
            }`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-live" />
            В эфир
          </button>
        )
      }
    >
      {notFound ? (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
          <p className="text-sm text-ink-muted">Такой камеры нет в списке.</p>
          <button
            onClick={() => navigate("/")}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover"
          >
            К списку камер
          </button>
        </div>
      ) : (
        <div className="flex h-full min-h-0 flex-col lg:flex-row">
          {/* Левая часть: видео + управление + таймлайн */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
            {/* Видео (16:9, но с потолком по высоте — иначе на широком экране
                оно раздувается и таймлайн уезжает под сгиб) */}
            <div
              className="mx-auto w-full shrink-0 bg-black"
              style={{ aspectRatio: "16 / 9", maxWidth: "calc(56vh * 16 / 9)" }}
            >
              {mode === "live" ? (
                <HlsVideo src={liveUrl(deviceId, view)} live onTime={onTime} className="h-full w-full" />
              ) : videoGone ? (
                <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
                  <Trash2 className="h-8 w-8 text-ink-faint" />
                  <p className="max-w-md text-sm text-ink-muted">
                    Видео за этот момент уже удалено из архива (он хранится ограниченное время).
                    <br />
                    Транскрипт и AI-разбор сохранены — они справа.
                  </p>
                </div>
              ) : archiveFrom !== null ? (
                <HlsVideo
                  key={`${archiveFrom}-${view}`}
                  src={archiveUrl(
                    deviceId,
                    new Date(archiveFrom).toISOString(),
                    new Date(archiveTo ?? dayStart + DAY_MS).toISOString(),
                    view,
                  )}
                  onTime={onTime}
                  onEnded={() => archiveTo !== null && seekTo(archiveTo + 1)}
                  className="h-full w-full"
                />
              ) : (
                <div className="flex h-full items-center justify-center px-6 text-center text-sm text-ink-muted">
                  {hasVideo
                    ? "Выберите участок с записью на таймлайне ниже, чтобы посмотреть архив."
                    : isPast
                      ? "За этот день записей нет."
                      : "За сегодня записей пока нет."}
                </div>
              )}
            </div>

            {/* Панель управления + таймлайн */}
            <div className="space-y-3 border-t border-hairline p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => changeDay(-1)}
                    className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted ring-1 ring-hairline hover:bg-white/5"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="min-w-[9.5rem] text-center text-sm text-ink">{fmtDate(dayStart)}</span>
                  <button
                    onClick={() => changeDay(1)}
                    disabled={isToday}
                    className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted ring-1 ring-hairline hover:bg-white/5 disabled:opacity-40"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                  {mode === "live" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-md bg-live/15 px-2 py-1 text-[12px] font-semibold uppercase tracking-wide text-live">
                      <span className="h-1.5 w-1.5 animate-live-blink rounded-full bg-live" />
                      Live
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-md bg-white/5 px-2 py-1 text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
                      <History className="h-3 w-3" />
                      Архив
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3">
                  <span className="tabular-nums text-sm text-ink-muted">
                    {mode === "live" ? <LiveClock /> : position !== null ? fmtClock(position) : "—"}
                  </span>

                  {/* Скачивание диапазона */}
                  <div className="relative">
                    <button
                      onClick={() => (dlOpen ? setDlOpen(false) : openDownload())}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white transition hover:bg-brand-hover"
                    >
                      <Download className="h-4 w-4" />
                      Скачать
                    </button>
                    {dlOpen && (
                      <>
                        <div className="fixed inset-0 z-40" onClick={() => setDlOpen(false)} />
                        <div className="absolute bottom-full right-0 z-50 mb-2 w-[19rem] max-w-[calc(100vw-2rem)] rounded-xl border border-hairline bg-elevated p-3.5 shadow-lift">
                          <div className="mb-3 flex items-baseline justify-between">
                            <span className="text-sm font-semibold text-ink">Скачать запись</span>
                            <span className="text-[11px] text-ink-faint">{fmtDate(dayStart)}</span>
                          </div>

                          <div className="grid grid-cols-2 gap-2.5">
                            <label className="block">
                              <span className="mb-1 block text-[11px] text-ink-muted">Начало</span>
                              <input
                                type="time"
                                value={dlFrom}
                                onChange={(e) => setDlFrom(e.target.value)}
                                style={{ colorScheme: "dark" }}
                                className="w-full rounded-lg border border-hairline bg-black/30 px-2.5 py-1.5 text-sm tabular-nums text-ink outline-none transition focus:border-brand"
                              />
                            </label>
                            <label className="block">
                              <span className="mb-1 block text-[11px] text-ink-muted">Конец</span>
                              <input
                                type="time"
                                value={dlTo}
                                onChange={(e) => setDlTo(e.target.value)}
                                style={{ colorScheme: "dark" }}
                                className="w-full rounded-lg border border-hairline bg-black/30 px-2.5 py-1.5 text-sm tabular-nums text-ink outline-none transition focus:border-brand"
                              />
                            </label>
                          </div>

                          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                            <span className="text-[11px] text-ink-faint">Быстро:</span>
                            <button
                              onClick={() => quickFill(60)}
                              className="rounded-md px-2 py-1 text-[11px] text-ink-muted ring-1 ring-hairline transition hover:bg-white/5 hover:text-ink"
                            >
                              1 час
                            </button>
                            <button
                              onClick={() => quickFill(360)}
                              className="rounded-md px-2 py-1 text-[11px] text-ink-muted ring-1 ring-hairline transition hover:bg-white/5 hover:text-ink"
                            >
                              6 часов
                            </button>
                            <button
                              onClick={() => {
                                setDlFrom("00:00");
                                setDlTo("23:59");
                              }}
                              className="rounded-md px-2 py-1 text-[11px] text-ink-muted ring-1 ring-hairline transition hover:bg-white/5 hover:text-ink"
                            >
                              Весь день
                            </button>
                          </div>

                          <button
                            onClick={download}
                            disabled={!dlValid}
                            className="mt-3.5 flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            <Download className="h-4 w-4" />
                            Скачать MP4
                          </button>
                          {!dlValid && (
                            <p className="mt-2 text-center text-[11px] text-danger">
                              «Конец» должен быть позже «Начала»
                            </p>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {views > 1 && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] text-ink-faint">Ракурс:</span>
                  {Array.from({ length: views }).map((_, i) => (
                    <button
                      key={i}
                      onClick={() => setView(i)}
                      className={`h-7 rounded-md px-3 text-[12px] font-medium transition ${
                        view === i
                          ? "bg-brand text-white"
                          : "text-ink-muted ring-1 ring-hairline hover:bg-white/5 hover:text-ink"
                      }`}
                    >
                      {i + 1}
                    </button>
                  ))}
                </div>
              )}

              <Timeline
                deviceId={deviceId}
                dayStart={dayStart}
                ranges={ranges}
                events={events}
                idle={idle}
                episodes={episodes}
                pins={pins}
                position={playhead}
                live={mode === "live"}
                onSeek={seekTo}
                onViewChange={(s, e) => setViewRange({ start: s, end: e })}
              />

              {blocks.length === 0 && !timelineQuery.isLoading && (
                <p className="text-center text-xs text-ink-faint">За этот день записей нет.</p>
              )}
            </div>
          </div>

          {/* Правая колонка: транскрипт / AI-сводка (на мобильном — заданная
              высота, чтобы внутренний скролл работал; на десктопе тянется по высоте) */}
          <div className="flex h-[65vh] min-h-0 shrink-0 flex-col border-t border-hairline lg:h-auto lg:w-[26rem] lg:border-l lg:border-t-0">
            <div className="flex gap-1 border-b border-hairline p-2">
              {(["transcript", "summary"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setRightTab(t)}
                  className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition ${
                    rightTab === t
                      ? "bg-brand text-white"
                      : "text-ink-muted ring-1 ring-hairline hover:bg-white/5 hover:text-ink"
                  }`}
                >
                  {t === "transcript" ? "Транскрипт" : "Сводка"}
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1 p-3">
              {rightTab === "transcript" ? (
                <Transcript
                  deviceId={deviceId}
                  dayStart={dayStart}
                  position={playhead}
                  live={mode === "live"}
                  onSeek={seekToTranscript}
                />
              ) : (
                <Conversations
                  conversations={conversations}
                  distractions={distractions}
                  loading={convQuery.isLoading}
                  onSeek={seekToTranscript}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
