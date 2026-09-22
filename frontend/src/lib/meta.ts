// Единый источник цветов и подписей для AI-разбора: типы эпизодов, настроение
// клиента, виды ключевых моментов, шкала оценок, роли, критерии. Раньше эти
// словари копировались по компонентам (Conversations/Search/Objections/Timeline/
// Transcript) и разъезжались — теперь один источник правды.
import { EpisodeType } from "../api";

export const TYPE_META: Record<EpisodeType, { label: string; color: string }> = {
  consultation: { label: "Консультация", color: "#22c55e" },
  sale: { label: "Продажа", color: "#14b8a6" },
  distraction: { label: "Отвлечение", color: "#f97316" },
  internal: { label: "Болтовня", color: "#6b7280" },
  other: { label: "Прочее", color: "#6b7280" },
};

export const SENTIMENT_META: Record<string, { label: string; color: string }> = {
  happy: { label: "Доволен", color: "#22c55e" },
  neutral: { label: "Нейтрально", color: "#6b7280" },
  hesitant: { label: "Сомневается", color: "#f59e0b" },
  unhappy: { label: "Недоволен", color: "#ef4444" },
};

// Виды ключевых моментов/возражений — общий словарь для пинов таймлайна,
// подсветки реплик и библиотеки возражений.
export const KIND_META: Record<string, { label: string; color: string }> = {
  objection: { label: "Возражение", color: "#f59e0b" },
  contra: { label: "Противопоказания", color: "#ef4444" },
  complaint: { label: "Жалоба", color: "#ef4444" },
  redflag: { label: "Red flag", color: "#ef4444" },
  upsell: { label: "Апселл", color: "#22c55e" },
  promise: { label: "Обещание", color: "#22c55e" },
  other: { label: "Момент", color: "#5b9bff" },
};

export const ROLE_LABELS: Record<string, string> = {
  master: "Мастер", seller: "Продажник", client: "Клиент", other: "—",
};

export const CRIT_LABELS: Record<string, string> = {
  greeting: "Приветствие", needs: "Потребности", contraindications: "Противопоказания",
  presentation: "Презентация", objections: "Возражения", upsell: "Апселл",
  next_step: "Запись", politeness: "Вежливость",
};

// 0–100: зелёный ≥80, янтарь ≥60, иначе красный.
export const scoreColor = (s: number) => (s >= 80 ? "#22c55e" : s >= 60 ? "#f59e0b" : "#ef4444");

export const kindColor = (kind: string) => (KIND_META[kind] ?? KIND_META.other).color;

export const speakerColor = (s: string) =>
  s === "Мастер" ? "#5b9bff" : s === "Продажник" ? "#14b8a6" : s === "Клиент" ? "#a78bfa" : "";

// Градиенты полос таймлайна для дорожки аналитики (насыщеннее плоских бейджей —
// читаемы на тёмном фоне). Ключи — только «содержательные» типы эпизодов.
export const EP_GRADIENT: Record<string, string> = {
  consultation: "linear-gradient(180deg, #34d399 0%, #059669 100%)",
  sale: "linear-gradient(180deg, #2dd4bf 0%, #0d9488 100%)",
  distraction: "linear-gradient(180deg, #fb923c 0%, #ea580c 100%)",
};

// Плоский цвет для легенды/точек (тёмный край градиента).
export const EP_SWATCH: Record<string, string> = {
  consultation: "#059669",
  sale: "#0d9488",
  distraction: "#ea580c",
};

// Структурные цвета самих полос записи (не «смысловые» — визуальные примитивы).
export const IDLE_SWATCH = "#3a4358";
export const EVENT_SWATCH = "#f59e0b";
