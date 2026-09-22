import HlsVideo from "./HlsVideo";
import { liveUrl } from "../api";

// Тонкая обёртка над HlsVideo для live-потока конкретного устройства.
export default function LivePlayer({
  deviceId,
  className,
}: {
  deviceId: string;
  className?: string;
}) {
  return <HlsVideo src={liveUrl(deviceId)} live className={className} />;
}
