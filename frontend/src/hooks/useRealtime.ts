import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Живые обновления панели через WebSocket (/api/ws).
 * При событии о новой записи мгновенно инвалидируем список камер и таймлайн.
 * Автопереподключение + пинг, чтобы соединение не засыпало на прокси.
 */
export function useRealtime() {
  const qc = useQueryClient();

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: number | undefined;
    let ping: number | undefined;

    const connect = () => {
      if (closed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/ws`);

      ws.onopen = () => {
        ping = window.setInterval(() => {
          if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 25000);
      };

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "segment") {
            qc.invalidateQueries({ queryKey: ["devices"] });
            if (msg.device_id) qc.invalidateQueries({ queryKey: ["timeline", msg.device_id] });
          } else if (msg.type === "transcript") {
            if (msg.device_id) qc.invalidateQueries({ queryKey: ["transcript", msg.device_id] });
          } else if (msg.type === "conversation") {
            if (msg.device_id) qc.invalidateQueries({ queryKey: ["conversations", msg.device_id] });
          } else if (msg.type === "screen") {
            // тихое отвлечение по кадрам приходит вместе с таймлайном
            if (msg.device_id) qc.invalidateQueries({ queryKey: ["timeline", msg.device_id] });
          }
        } catch {
          /* не JSON — игнорируем */
        }
      };

      const reconnect = () => {
        window.clearInterval(ping);
        ws = null;
        if (!closed) retry = window.setTimeout(connect, 3000);
      };
      ws.onclose = reconnect;
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      window.clearInterval(ping);
      ws?.close();
    };
  }, [qc]);
}
