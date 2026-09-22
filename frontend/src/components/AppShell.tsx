import { ReactNode, useState } from "react";
import { Menu } from "lucide-react";
import Sidebar from "./Sidebar";
import { useAuth } from "../auth";

export default function AppShell({
  title,
  subtitle,
  actions,
  leading,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  leading?: ReactNode; // напр. кнопка «назад» на странице камеры
  children: ReactNode;
}) {
  const { username, logout } = useAuth();
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="flex h-full">
      <Sidebar
        open={navOpen}
        onClose={() => setNavOpen(false)}
        username={username}
        onLogout={logout}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Верхняя панель */}
        <header className="sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-hairline bg-bg/80 px-4 backdrop-blur-md sm:px-6">
          <button
            onClick={() => setNavOpen(true)}
            className="rounded-lg p-2 text-ink-muted hover:bg-white/5 lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>

          {leading}

          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-semibold tracking-tight text-ink">
              {title}
            </h1>
            {subtitle && (
              <div className="truncate text-[13px] text-ink-muted">{subtitle}</div>
            )}
          </div>

          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
