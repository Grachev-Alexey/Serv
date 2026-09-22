// Скелетоны загрузки вместо голого «Загрузка…». Ширины детерминированы (без
// random), чтобы не мигали при перерисовке.

export function SkeletonLines({ rows = 7 }: { rows?: number }) {
  return (
    <div className="space-y-2.5 px-1 py-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2.5">
          <div className="shimmer h-3 w-10 shrink-0 rounded bg-elevated" />
          <div
            className="shimmer h-3 rounded bg-elevated"
            style={{ width: `${55 + ((i * 29) % 40)}%` }}
          />
        </div>
      ))}
    </div>
  );
}

export function SkeletonCards({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-2 p-1">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-hairline bg-black/20 p-2.5">
          <div className="mb-2 flex gap-2">
            <div className="shimmer h-4 w-24 rounded bg-elevated" />
            <div className="shimmer h-4 w-14 rounded bg-elevated" />
          </div>
          <div className="shimmer mb-1.5 h-3 rounded bg-elevated" style={{ width: `${70 - ((i * 13) % 25)}%` }} />
          <div className="shimmer h-3 rounded bg-elevated" style={{ width: `${45 + ((i * 17) % 30)}%` }} />
        </div>
      ))}
    </div>
  );
}
