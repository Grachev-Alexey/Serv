import { Component, ErrorInfo, ReactNode } from "react";
import { TriangleAlert } from "lucide-react";

// Ловит исключения рендера в дереве — вместо белого экрана показывает понятное
// сообщение и кнопку «Обновить». Классовый компонент: хуки границы ошибок не умеют.
export default class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Сбой интерфейса:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
          <div className="grid h-14 w-14 place-items-center rounded-2xl bg-danger/15 text-danger ring-1 ring-danger/30">
            <TriangleAlert className="h-7 w-7" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-ink">Что-то сломалось</h1>
            <p className="mt-1 max-w-sm text-sm text-ink-muted">
              Обновите страницу. Если повторяется — сообщите, что делали перед этим.
            </p>
          </div>
          <button
            onClick={() => window.location.reload()}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-hover"
          >
            Обновить
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
