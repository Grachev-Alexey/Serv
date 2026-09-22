export function timeAgo(iso: string | null): string {
  if (!iso) return "нет данных";
  const then = new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime();
  const sec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (sec < 10) return "только что";
  if (sec < 60) return `${sec} с назад`;
  if (sec < 3600) return `${Math.floor(sec / 60)} мин назад`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} ч назад`;
  return `${Math.floor(sec / 86400)} дн назад`;
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${units[i]}`;
}
