import { memo, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Conversation } from "../api";
import {
  TYPE_META, ROLE_LABELS, CRIT_LABELS, SENTIMENT_META, scoreColor, kindColor,
} from "../lib/meta";
import { SkeletonCards } from "./ui/Skeleton";

const fmtClock = (ms: number) =>
  new Date(ms).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const fmtHM = (ms: number) =>
  new Date(ms).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });

// Экран считаем «отвлечением», если половина и более просмотренных кадров —
// развлечение (а для эпизодов без кадров — по типу эпизода).
const screenIsDistraction = (c: Conversation) => {
  if (!c.screens?.length) return c.type === "distraction";
  return c.screens.filter((s) => s.distraction).length * 2 >= c.screens.length;
};

function Conversations({
  conversations,
  distractions = [],
  loading = false,
  onSeek,
}: {
  conversations: Conversation[];
  distractions?: { start: number; end: number; label?: string }[];
  loading?: boolean;
  onSeek: (ms: number) => void;
}) {
  // Показываем содержательные эпизоды (пустой «other» без сводки — прячем).
  const convs = conversations.filter((c) => c.type !== "other" || c.summary || c.highlights.length);

  // Дневная сводка одним взглядом. Отвлечение = минуты по речи + молчаливое по экрану.
  const rollup = useMemo(() => {
    const cons = conversations.filter((c) => c.type === "consultation" || c.type === "sale");
    const scored = cons.filter((c) => c.score !== null);
    const avg = scored.length
      ? Math.round(scored.reduce((s, c) => s + (c.score ?? 0), 0) / scored.length)
      : null;
    const sales = conversations.filter((c) => c.type === "sale").length;
    const distractMs =
      conversations.filter((c) => c.type === "distraction").reduce((s, c) => s + (c.end - c.start), 0) +
      distractions.reduce((s, d) => s + (d.end - d.start), 0);
    return { cons: cons.length, avg, sales, distractMin: Math.round(distractMs / 60000) };
  }, [conversations, distractions]);

  const statusQuery = useQuery({
    queryKey: ["analyzeStatus"],
    queryFn: () => api.analyzeStatus(),
    refetchInterval: 30000,
  });
  const st = statusQuery.data;
  let dotColor = "#6b7280";
  let dotTip = "AI-анализ выключен (нет ключа Mistral)";
  if (st?.enabled) {
    const failing = !!st.last_error_at && (!st.last_ok_at || st.last_error_at > st.last_ok_at);
    const tail = `Разборов: ${st.ok}, ошибок: ${st.failed}, повторов: ${st.retries}`;
    dotColor = failing ? "#f59e0b" : "#22c55e";
    dotTip = failing
      ? `Проблема с AI-анализом: ${st.last_error ?? "ошибка"}. ${tail}`
      : `AI-анализ работает (${st.model}). ${tail}`;
  }

  // Здоровье зрения по кадрам (Pixtral) — отдельная точка, показываем если включено.
  const visionQuery = useQuery({
    queryKey: ["visionStatus"],
    queryFn: () => api.visionStatus(),
    refetchInterval: 30000,
  });
  const vs = visionQuery.data;
  let vDot = "#22c55e";
  let vTip = "";
  if (vs?.enabled) {
    const failing = !!vs.last_error_at && (!vs.last_ok_at || vs.last_error_at > vs.last_ok_at);
    const tail = `Кадров: ${vs.ok}, ошибок: ${vs.failed}`;
    vDot = failing ? "#f59e0b" : "#22c55e";
    vTip = failing
      ? `Проблема со зрением по кадрам: ${vs.last_error ?? "ошибка"}. ${tail}`
      : `Зрение по кадрам работает (${vs.model}). ${tail}`;
  }

  const cards = useMemo(
    () =>
      convs.map((c) => {
        const meta = TYPE_META[c.type] ?? TYPE_META.other;
        return (
          <div key={c.id} className="rounded-lg border border-hairline bg-black/20 p-3">
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <span
                className="rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white"
                style={{ background: meta.color }}
              >
                {meta.label}
              </span>
              <button
                onClick={() => onSeek(c.start)}
                className="font-mono text-[12px] tabular-nums text-ink-faint hover:text-ink"
                title="К началу эпизода"
              >
                {fmtHM(c.start)}–{fmtHM(c.end)}
              </button>
              {c.sentiment && SENTIMENT_META[c.sentiment] && (
                <span
                  className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-white"
                  style={{ background: SENTIMENT_META[c.sentiment].color }}
                  title="Настроение клиента"
                >
                  {SENTIMENT_META[c.sentiment].label}
                </span>
              )}
              {c.score !== null && (
                <span
                  className="ml-auto rounded px-1.5 py-0.5 text-[12px] font-bold text-white"
                  style={{ background: scoreColor(c.score) }}
                  title="Общая оценка"
                >
                  {c.score}
                </span>
              )}
            </div>

            {c.title && <p className="mb-1 text-[13px] font-medium text-ink">{c.title}</p>}

            {c.participants.length > 0 && (
              <div className="mb-1.5 flex flex-wrap gap-1">
                {c.participants.map((p, i) => (
                  <span key={i} className="rounded bg-white/5 px-1.5 py-0.5 text-[11px] text-ink-muted">
                    {ROLE_LABELS[p.role] ?? p.role}
                    {p.note ? `: ${p.note}` : ""}
                  </span>
                ))}
                {c.seller_score !== null && (
                  <span
                    className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-white"
                    style={{ background: scoreColor(c.seller_score) }}
                    title="Оценка продажника"
                  >
                    Продажник {c.seller_score}
                  </span>
                )}
              </div>
            )}

            {c.screen && (
              <div className="mb-1.5">
                <span
                  className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
                  style={
                    screenIsDistraction(c)
                      ? { background: "rgba(249,115,22,0.16)", color: "#fb923c" }
                      : { background: "rgba(91,155,255,0.12)", color: "#8b98ad" }
                  }
                  title="Экран"
                >
                  Экран: {c.screen}
                </span>
              </div>
            )}

            {c.summary && <p className="mb-1.5 text-[14px] leading-snug text-ink">{c.summary}</p>}

            {Object.keys(c.criteria).length > 0 && (
              <div className="mb-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5">
                {Object.entries(c.criteria).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-[12px]">
                    <span className="truncate text-ink-faint">{CRIT_LABELS[k] ?? k}</span>
                    <span style={{ color: scoreColor(v * 10) }}>{v}/10</span>
                  </div>
                ))}
              </div>
            )}

            {c.flags.length > 0 && (
              <ul className="mb-1.5 space-y-0.5">
                {c.flags.map((f, i) => (
                  <li key={i} className="text-[12px] text-danger">— {f}</li>
                ))}
              </ul>
            )}

            {c.highlights.length > 0 && (
              <div className="space-y-0.5">
                {c.highlights.map((h, i) => (
                  <button
                    key={i}
                    onClick={() => onSeek(h.t)}
                    className="flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left transition hover:bg-white/5"
                  >
                    <span
                      className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ background: kindColor(h.kind) }}
                    />
                    <span className="shrink-0 pt-px font-mono text-[12px] tabular-nums text-ink-faint">
                      {fmtClock(h.t)}
                    </span>
                    <span className="text-[13px] leading-snug text-ink-muted">{h.text}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      }),
    [convs, onSeek],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-hairline px-1 pb-2">
        <span className="text-[14px] font-medium text-ink">Сводка</span>
        <span
          className="h-2 w-2 shrink-0 cursor-help rounded-full"
          style={{ background: dotColor }}
          title={dotTip}
        />
        {vs?.enabled && (
          <span
            className="h-2 w-2 shrink-0 cursor-help rounded-full ring-1 ring-white/20"
            style={{ background: vDot }}
            title={vTip}
          />
        )}
        <span className="ml-auto text-[12px] text-ink-faint">
          {convs.length ? `${convs.length} эпизодов` : ""}
        </span>
      </div>

      {convs.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 border-b border-hairline px-1 py-2 text-[12px] text-ink-muted">
          <span>Консультаций: <b className="text-ink">{rollup.cons}</b></span>
          {rollup.avg !== null && (
            <span>Ср. оценка: <b style={{ color: scoreColor(rollup.avg) }}>{rollup.avg}</b></span>
          )}
          <span>Продаж: <b className="text-ink">{rollup.sales}</b></span>
          {rollup.distractMin > 0 && (
            <span>Отвлечение: <b className="text-ink">{rollup.distractMin} мин</b></span>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto py-2">
        {distractions.length > 0 && (
          <div className="rounded-lg border border-hairline bg-black/20 p-2.5">
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
              Тихое отвлечение (по экрану)
            </div>
            <div className="space-y-0.5">
              {distractions.map((d, i) => (
                <button
                  key={i}
                  onClick={() => onSeek(d.start)}
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left transition hover:bg-white/5"
                >
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "#f97316" }} />
                  <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-faint">
                    {fmtHM(d.start)}–{fmtHM(d.end)}
                  </span>
                  <span className="truncate text-[13px] text-ink-muted">
                    {d.label || "экран: развлечение"}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        {loading && convs.length === 0 ? (
          <SkeletonCards count={4} />
        ) : convs.length === 0 && distractions.length === 0 ? (
          <p className="px-2 py-3 text-center text-[13px] text-ink-faint">
            {st && !st.enabled
              ? "AI-анализ выключен (нет ключа Mistral)."
              : "Разговоры за этот день ещё не разобраны."}
          </p>
        ) : (
          cards
        )}
      </div>
    </div>
  );
}

export default memo(Conversations);
