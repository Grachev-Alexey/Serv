export default function CameraSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl bg-surface ring-1 ring-hairline">
      <div className="shimmer aspect-video bg-elevated" />
      <div className="space-y-3 p-4">
        <div className="shimmer h-4 w-2/3 rounded bg-elevated" />
        <div className="flex justify-between">
          <div className="shimmer h-3 w-24 rounded bg-elevated" />
          <div className="shimmer h-3 w-16 rounded bg-elevated" />
        </div>
      </div>
    </div>
  );
}
