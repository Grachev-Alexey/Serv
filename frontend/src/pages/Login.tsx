import { useState, FormEvent } from "react";
import { User, Lock, Eye, EyeOff } from "lucide-react";
import { useAuth } from "../auth";
import { ApiError } from "../api";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Неверный логин или пароль"
          : "Ошибка входа. Попробуйте ещё раз.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden p-4">
      {/* Декоративные подсветки */}
      <div className="pointer-events-none absolute -left-40 top-0 h-96 w-96 rounded-full bg-brand/20 blur-[120px]" />
      <div className="pointer-events-none absolute -right-40 bottom-0 h-96 w-96 rounded-full bg-ok/10 blur-[120px]" />

      <div className="w-full max-w-sm animate-fade-in">
        {/* Бренд */}
        <div className="mb-8 flex flex-col items-center text-center">
          <h1 className="text-3xl font-semibold tracking-tight text-ink">Виви</h1>
          <p className="mt-1 text-sm text-ink-muted">Мониторинг</p>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-2xl border border-hairline bg-surface/80 p-6 shadow-card backdrop-blur-xl"
        >
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-[13px] font-medium text-ink-muted">
                Логин
              </label>
              <Input
                icon={<User className="h-[18px] w-[18px]" />}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoFocus
                autoComplete="username"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-[13px] font-medium text-ink-muted">
                Пароль
              </label>
              <Input
                icon={<Lock className="h-[18px] w-[18px]" />}
                type={show ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
                trailing={
                  <button
                    type="button"
                    onClick={() => setShow((s) => !s)}
                    className="grid h-8 w-8 place-items-center rounded-md text-ink-faint hover:text-ink-muted"
                    tabIndex={-1}
                  >
                    {show ? <EyeOff className="h-[18px] w-[18px]" /> : <Eye className="h-[18px] w-[18px]" />}
                  </button>
                }
              />
            </div>

            {error && (
              <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                {error}
              </div>
            )}

            <Button type="submit" disabled={busy} className="w-full">
              {busy ? (
                <>
                  <Spinner className="h-4 w-4" /> Вход…
                </>
              ) : (
                "Войти"
              )}
            </Button>
          </div>
        </form>

        <p className="mt-6 text-center text-xs text-ink-faint">
          Защищённый доступ · сессия шифруется
        </p>
      </div>
    </div>
  );
}
