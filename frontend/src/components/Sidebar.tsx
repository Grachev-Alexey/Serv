import { Video, LogOut, X, Settings } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

interface NavItem {
  label: string;
  icon: typeof Video;
  to: string;
  match: (pathname: string) => boolean;
}

const NAV: NavItem[] = [
  { label: "Камеры", icon: Video, to: "/", match: (p) => p === "/" || p.startsWith("/camera") },
  { label: "Настройки", icon: Settings, to: "/settings", match: (p) => p.startsWith("/settings") },
];

export default function Sidebar({
  open,
  onClose,
  username,
  onLogout,
}: {
  open: boolean;
  onClose: () => void;
  username: string | null;
  onLogout: () => void;
}) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <>
      {/* Затемнение под выдвижным меню на мобильных */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-52 flex-col border-r border-hairline bg-surface/95 backdrop-blur transition-transform duration-200 lg:static lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Бренд */}
        <div className="flex h-16 items-center justify-between px-5">
          <div className="leading-tight">
            <div className="text-[17px] font-semibold tracking-tight text-ink">Виви</div>
            <div className="text-[11px] text-ink-faint">Мониторинг</div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-ink-muted hover:bg-white/5 lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Навигация */}
        <nav className="flex-1 space-y-1 px-3 py-2">
          {NAV.map((item) => {
            const active = item.match(pathname);
            return (
              <button
                key={item.label}
                onClick={() => {
                  navigate(item.to);
                  onClose();
                }}
                className={`group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                  active
                    ? "bg-brand/12 text-ink ring-1 ring-brand/25"
                    : "text-ink-muted hover:bg-white/5 hover:text-ink"
                }`}
              >
                <item.icon className={`h-[18px] w-[18px] ${active ? "text-brand" : ""}`} />
                <span className="flex-1 text-left">{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Пользователь */}
        <div className="border-t border-hairline p-3">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand/40 to-brand/10 text-sm font-semibold text-ink ring-1 ring-white/10">
              {(username || "?").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-ink">{username}</div>
            </div>
            <button
              onClick={onLogout}
              title="Выйти"
              className="rounded-md p-2 text-ink-muted transition hover:bg-danger/10 hover:text-danger"
            >
              <LogOut className="h-[18px] w-[18px]" />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
