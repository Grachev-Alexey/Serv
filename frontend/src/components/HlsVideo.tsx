import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, Loader2, Play, Pause, Volume2, VolumeX,
  Maximize, Minimize, RotateCcw, RotateCw,
} from "lucide-react";

type Status = "loading" | "ready" | "error";

const RATES = [1, 1.5, 2, 4];

function fmt(s: number): string {
  if (!isFinite(s) || s < 0) s = 0;
  s = Math.floor(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function fracFromPointer(el: HTMLElement, clientX: number): number {
  const r = el.getBoundingClientRect();
  return Math.min(1, Math.max(0, (clientX - r.left) / r.width));
}

export default function HlsVideo({
  src,
  live = false,
  className = "",
  onTime,
  onEnded,
}: {
  src: string;
  live?: boolean;
  className?: string;
  onTime?: (seconds: number, wallClockMs?: number) => void;
  onEnded?: () => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<import("hls.js").default | null>(null);
  const onTimeRef = useRef(onTime);
  onTimeRef.current = onTime;
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;
  const hideTimer = useRef<number | undefined>(undefined);

  const [status, setStatus] = useState<Status>("loading");
  const [playing, setPlaying] = useState(false);
  // Звук/громкость запоминаем между перемотками и сессиями (localStorage).
  const [muted, setMuted] = useState(() => {
    try { const v = localStorage.getItem("vivi.muted"); return v === null ? true : v === "1"; } catch { return true; }
  });
  const [volume, setVolume] = useState(() => {
    try { const v = parseFloat(localStorage.getItem("vivi.volume") ?? "1"); return isFinite(v) ? Math.min(1, Math.max(0, v)) : 1; } catch { return 1; }
  });
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [rate, setRate] = useState(1);
  const [fs, setFs] = useState(false);
  const [ctrlShown, setCtrlShown] = useState(true);

  // Актуальные значения звука для использования внутри эффектов загрузки.
  const mutedRef = useRef(muted);
  mutedRef.current = muted;
  const volumeRef = useRef(volume);
  volumeRef.current = volume;

  // Сохраняем выбор звука между перемотками/сессиями.
  useEffect(() => {
    try { localStorage.setItem("vivi.muted", muted ? "1" : "0"); } catch { /* приватный режим */ }
  }, [muted]);
  useEffect(() => {
    try { localStorage.setItem("vivi.volume", String(volume)); } catch { /* приватный режим */ }
  }, [volume]);

  // Старт воспроизведения с сохранённым звуком. Если автоплей со звуком
  // заблокирован браузером — играем без звука (включат кликом = жестом).
  const startPlayback = useCallback((video: HTMLVideoElement) => {
    video.muted = mutedRef.current;
    video.volume = volumeRef.current;
    video.play().catch(() => {
      if (!video.muted) {
        video.muted = true;
        setMuted(true);
        video.play().catch(() => {});
      }
    });
  }, []);

  // Загрузка hls.js (по требованию, отдельный чанк)
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    setStatus("loading");
    setCurrent(0);
    setDuration(0);
    let hls: import("hls.js").default | null = null;
    let cancelled = false;

    (async () => {
      const { default: Hls } = await import("hls.js");
      if (cancelled) return;
      if (Hls.isSupported()) {
        hls = new Hls({
          liveSyncDurationCount: 2,
          backBufferLength: live ? 30 : 90,
          xhrSetup: (xhr) => {
            xhr.withCredentials = true;
          },
        });
        hlsRef.current = hls;
        hls.loadSource(src);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          setStatus("ready");
          startPlayback(video);
        });
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (!data.fatal) return;
          if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls?.startLoad();
          else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls?.recoverMediaError();
          else if (!cancelled) setStatus("error");
        });
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = src;
        video.addEventListener("loadedmetadata", () => {
          setStatus("ready");
          startPlayback(video);
        });
        video.addEventListener("error", () => !cancelled && setStatus("error"));
      } else {
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      hlsRef.current = null;
      hls?.destroy();
    };
  }, [src, live, startPlayback]);

  // События <video>
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = mutedRef.current;
    v.volume = volumeRef.current;
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onTimeUpdate = () => {
      setCurrent(v.currentTime);
      // playingDate приходит из EXT-X-PROGRAM-DATE-TIME — это время съёмки
      // текущего кадра. Для нативного HLS (Safari) берём getStartDate().
      let wall: number | undefined;
      const pd = hlsRef.current?.playingDate;
      if (pd) wall = pd.getTime();
      else if (typeof (v as unknown as { getStartDate?: () => Date }).getStartDate === "function") {
        const sd = (v as unknown as { getStartDate: () => Date }).getStartDate();
        if (sd && !Number.isNaN(sd.getTime())) wall = sd.getTime() + v.currentTime * 1000;
      }
      onTimeRef.current?.(v.currentTime, wall);
      if (v.buffered.length) setBuffered(v.buffered.end(v.buffered.length - 1));
    };
    const onDuration = () => setDuration(v.duration || 0);
    const onVolume = () => {
      setMuted(v.muted);
      setVolume(v.volume);
    };
    const onRate = () => setRate(v.playbackRate);
    const onEndedEv = () => onEndedRef.current?.();
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("timeupdate", onTimeUpdate);
    v.addEventListener("durationchange", onDuration);
    v.addEventListener("volumechange", onVolume);
    v.addEventListener("ratechange", onRate);
    v.addEventListener("ended", onEndedEv);
    return () => {
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("timeupdate", onTimeUpdate);
      v.removeEventListener("durationchange", onDuration);
      v.removeEventListener("volumechange", onVolume);
      v.removeEventListener("ratechange", onRate);
      v.removeEventListener("ended", onEndedEv);
    };
  }, []);

  useEffect(() => {
    const onFsChange = () => setFs(document.fullscreenElement === wrapRef.current);
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play().catch(() => {});
    else v.pause();
  }, []);

  const skip = useCallback((delta: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.min(v.duration || 0, Math.max(0, v.currentTime + delta));
  }, []);

  const toggleMute = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    if (!v.muted && v.volume === 0) v.volume = 1;
  };

  const setVol = (val: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.volume = val;
    v.muted = val === 0;
  };

  const cycleRate = () => {
    const v = videoRef.current;
    if (!v) return;
    v.playbackRate = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
  };

  const seekFrac = (frac: number) => {
    const v = videoRef.current;
    if (!v || !duration) return;
    v.currentTime = frac * duration;
  };

  const toggleFs = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen();
    else wrapRef.current?.requestFullscreen?.();
  }, []);

  const showControls = useCallback(() => {
    setCtrlShown(true);
    window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      if (!videoRef.current?.paused) setCtrlShown(false);
    }, 2600);
  }, []);

  // Клавиатура
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === " ") { e.preventDefault(); togglePlay(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); skip(-5); }
      else if (e.key === "ArrowRight") { e.preventDefault(); skip(5); }
      else if (e.key.toLowerCase() === "m") toggleMute();
      else if (e.key.toLowerCase() === "f") toggleFs();
      showControls();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [togglePlay, skip, toggleFs, showControls]);

  const scrubRef = useRef<HTMLDivElement>(null);
  const volRef = useRef<HTMLDivElement>(null);

  const progress = duration ? (current / duration) * 100 : 0;
  const bufPct = duration ? (buffered / duration) * 100 : 0;
  const volPct = (muted ? 0 : volume) * 100;

  return (
    <div
      ref={wrapRef}
      className={`group relative bg-black ${className}`}
      onPointerMove={showControls}
      onMouseLeave={() => !videoRef.current?.paused && setCtrlShown(false)}
    >
      <video ref={videoRef} className="h-full w-full" playsInline onClick={togglePlay} />

      {status === "loading" && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/40 text-ink-muted">
          <Loader2 className="h-7 w-7 animate-spin" />
          <span className="text-sm">{live ? "Подключение к потоку…" : "Загрузка записи…"}</span>
        </div>
      )}

      {status === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/60 text-center text-ink-muted">
          <AlertTriangle className="h-7 w-7 text-warn" />
          <span className="max-w-xs text-sm">
            {live
              ? "Поток недоступен. Камера офлайн или ещё не прислала сегменты."
              : "Здесь нет записи. Выберите участок на таймлайне."}
          </span>
        </div>
      )}

      {/* Большая кнопка play по центру, когда на паузе */}
      {status === "ready" && !playing && (
        <button
          onClick={togglePlay}
          className="absolute inset-0 z-[1] flex items-center justify-center"
        >
          <span className="grid h-16 w-16 place-items-center rounded-full bg-black/55 text-white ring-1 ring-white/20 backdrop-blur transition hover:scale-105 hover:bg-black/70">
            <Play className="h-7 w-7 translate-x-0.5 fill-current" />
          </span>
        </button>
      )}

      {/* Панель управления */}
      <div
        className={`absolute inset-x-0 bottom-0 z-[2] bg-gradient-to-t from-black/90 via-black/50 to-transparent px-4 pb-3 pt-10 transition-opacity duration-200 ${
          ctrlShown ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      >
        {/* Скраббер (архив) */}
        {!live && (
          <div
            ref={scrubRef}
            onPointerDown={(e) => {
              scrubRef.current?.setPointerCapture(e.pointerId);
              seekFrac(fracFromPointer(scrubRef.current!, e.clientX));
            }}
            onPointerMove={(e) => e.buttons === 1 && seekFrac(fracFromPointer(scrubRef.current!, e.clientX))}
            className="group/sc relative mb-2.5 flex h-4 cursor-pointer touch-none items-center"
          >
            <div className="relative h-1 w-full rounded-full bg-white/20 transition-all group-hover/sc:h-1.5">
              <div className="absolute inset-y-0 left-0 rounded-full bg-white/30" style={{ width: `${bufPct}%` }} />
              <div className="absolute inset-y-0 left-0 rounded-full bg-brand" style={{ width: `${progress}%` }} />
              <div
                className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white opacity-0 shadow ring-2 ring-brand transition group-hover/sc:opacity-100"
                style={{ left: `${progress}%` }}
              />
            </div>
          </div>
        )}

        <div className="flex items-center gap-2 text-white">
          <button onClick={togglePlay} title="Пробел" className="grid h-9 w-9 place-items-center rounded-lg hover:bg-white/12">
            {playing ? <Pause className="h-5 w-5 fill-current" /> : <Play className="h-5 w-5 fill-current" />}
          </button>

          {!live && (
            <>
              <button onClick={() => skip(-10)} title="−10 сек (←)" className="grid h-9 w-9 place-items-center rounded-lg hover:bg-white/12">
                <RotateCcw className="h-[18px] w-[18px]" />
              </button>
              <button onClick={() => skip(10)} title="+10 сек (→)" className="grid h-9 w-9 place-items-center rounded-lg hover:bg-white/12">
                <RotateCw className="h-[18px] w-[18px]" />
              </button>
            </>
          )}

          {/* Громкость */}
          <div className="group/vol flex items-center">
            <button onClick={toggleMute} title="Звук (M)" className="grid h-9 w-9 place-items-center rounded-lg hover:bg-white/12">
              {muted || volume === 0 ? <VolumeX className="h-5 w-5" /> : <Volume2 className="h-5 w-5" />}
            </button>
            <div
              ref={volRef}
              onPointerDown={(e) => {
                volRef.current?.setPointerCapture(e.pointerId);
                setVol(fracFromPointer(volRef.current!, e.clientX));
              }}
              onPointerMove={(e) => e.buttons === 1 && setVol(fracFromPointer(volRef.current!, e.clientX))}
              className="relative flex h-9 w-0 cursor-pointer touch-none items-center overflow-hidden opacity-0 transition-all duration-200 group-hover/vol:w-20 group-hover/vol:opacity-100"
            >
              <div className="relative mx-1 h-1 w-full rounded-full bg-white/25">
                <div className="absolute inset-y-0 left-0 rounded-full bg-white" style={{ width: `${volPct}%` }} />
                <div className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow" style={{ left: `${volPct}%` }} />
              </div>
            </div>
          </div>

          {live ? (
            <span className="ml-1 inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-live">
              <span className="h-1.5 w-1.5 animate-live-blink rounded-full bg-live" /> Прямой эфир
            </span>
          ) : (
            <span className="ml-1 tabular-nums text-[13px] text-white/85">
              {fmt(current)} <span className="text-white/40">/ {fmt(duration)}</span>
            </span>
          )}

          <div className="flex-1" />

          {!live && (
            <button
              onClick={cycleRate}
              title="Скорость воспроизведения"
              className="h-8 min-w-[2.75rem] rounded-lg px-2 text-[13px] font-semibold text-white/85 hover:bg-white/12"
            >
              {rate}×
            </button>
          )}

          <button onClick={toggleFs} title="Полный экран (F)" className="grid h-9 w-9 place-items-center rounded-lg hover:bg-white/12">
            {fs ? <Minimize className="h-5 w-5" /> : <Maximize className="h-5 w-5" />}
          </button>
        </div>
      </div>
    </div>
  );
}
