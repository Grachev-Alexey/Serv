import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Users, Bot, Plus, Trash2, Check, RotateCcw } from "lucide-react";
import AppShell from "../components/AppShell";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";
import { api, ApiError, Studio, PanelUser } from "../api";
import { useAuth } from "../auth";

type Tab = "studios" | "users" | "prompts";

const TZ_OPTIONS = [
  "Europe/Kaliningrad",
  "Europe/Moscow",
  "Europe/Samara",
  "Asia/Yekaterinburg",
  "Asia/Omsk",
  "Asia/Novosibirsk",
  "Asia/Krasnoyarsk",
  "Asia/Irkutsk",
  "Asia/Yakutsk",
  "Asia/Vladivostok",
];

const selectCls =
  "h-10 rounded-lg border border-hairline bg-black/30 px-2 text-sm text-ink outline-none focus:border-brand";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-hairline bg-surface/60 p-4">
      <h2 className="mb-3 text-sm font-semibold text-ink">{title}</h2>
      {children}
    </section>
  );
}

function Err({ e }: { e: unknown }) {
  if (!e) return null;
  return <p className="mt-2 text-[12px] text-danger">{e instanceof ApiError ? e.message : String(e)}</p>;
}

/* ─────────────────────────── Студии ─────────────────────────── */
function StudiosTab() {
  const qc = useQueryClient();
  const studios = useQuery({ queryKey: ["studios"], queryFn: api.studios });
  const devices = useQuery({ queryKey: ["devices"], queryFn: api.devices });
  const [draft, setDraft] = useState({ name: "", network: "", tz: "Europe/Moscow" });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["studios"] });
    qc.invalidateQueries({ queryKey: ["devices"] });
    qc.invalidateQueries({ queryKey: ["networks"] });
  };
  const create = useMutation({
    mutationFn: api.createStudio,
    onSuccess: () => { setDraft({ name: "", network: "", tz: "Europe/Moscow" }); invalidate(); },
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name: string; network: string; tz: string } }) =>
      api.updateStudio(id, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: api.deleteStudio, onSuccess: invalidate });
  const assign = useMutation({
    mutationFn: ({ d, s }: { d: string; s: number | null }) => api.assignDevice(d, s),
    onSuccess: invalidate,
  });

  if (studios.isLoading) return <Spinner />;

  return (
    <div className="space-y-4">
      <Section title="Новая студия">
        <div className="flex flex-wrap gap-2">
          <Input placeholder="Название" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="w-56" />
          <Input placeholder="Сеть" value={draft.network} onChange={(e) => setDraft({ ...draft, network: e.target.value })} className="w-44" />
          <select className={selectCls} value={draft.tz} onChange={(e) => setDraft({ ...draft, tz: e.target.value })}>
            {TZ_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <Button disabled={!draft.name.trim() || create.isPending} onClick={() => create.mutate(draft)}>
            <Plus className="h-4 w-4" /> Добавить
          </Button>
        </div>
        <Err e={create.error} />
      </Section>

      <Section title="Студии">
        <div className="space-y-2">
          {(studios.data ?? []).map((s: Studio) => (
            <div key={s.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-hairline bg-black/20 p-3">
              <Input defaultValue={s.name} className="w-52" onBlur={(e) => e.target.value !== s.name && update.mutate({ id: s.id, body: { ...s, name: e.target.value } })} />
              <Input defaultValue={s.network} className="w-40" onBlur={(e) => e.target.value !== s.network && update.mutate({ id: s.id, body: { ...s, network: e.target.value } })} />
              <select className={selectCls} value={s.tz} onChange={(e) => update.mutate({ id: s.id, body: { ...s, tz: e.target.value } })}>
                {TZ_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <span className="text-[12px] text-ink-muted">{s.devices.length}</span>
              <Button variant="danger" size="sm" className="ml-auto" onClick={() => remove.mutate(s.id)}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
        <Err e={update.error || remove.error} />
      </Section>

      <Section title="Камеры">
        <div className="space-y-1.5">
          {(devices.data ?? []).map((d) => (
            <div key={d.device_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-hairline bg-black/20 px-3 py-2">
              <span className="min-w-52 text-sm text-ink">{d.friendly_name}</span>
              <span className={`text-[11px] ${d.online ? "text-emerald-400" : "text-ink-muted"}`}>
                {d.online ? "онлайн" : "офлайн"}
              </span>
              <select
                className={`ml-auto ${selectCls} h-9`}
                value={d.studio_id ?? ""}
                onChange={(e) => assign.mutate({ d: d.device_id, s: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">—</option>
                {(studios.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>{(s.network ? s.network + " / " : "") + s.name}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <Err e={assign.error} />
      </Section>
    </div>
  );
}

/* ────────────────────────── Пользователи ────────────────────────── */
function UsersTab() {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  const networks = useQuery({ queryKey: ["networks"], queryFn: api.networks });
  const [draft, setDraft] = useState({ username: "", password: "", is_admin: false, network: "" });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["users"] });

  const create = useMutation({
    mutationFn: api.createUser,
    onSuccess: () => { setDraft({ username: "", password: "", is_admin: false, network: "" }); invalidate(); },
  });
  const setNet = useMutation({
    mutationFn: ({ u, n }: { u: string; n: string }) => api.setUserNetwork(u, n),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: api.deleteUser, onSuccess: invalidate });

  if (users.isLoading) return <Spinner />;
  const nets = networks.data ?? [];

  return (
    <div className="space-y-4">
      <Section title="Новый пользователь">
        <div className="flex flex-wrap items-center gap-2">
          <Input placeholder="Логин" value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} className="w-44" />
          <Input placeholder="Пароль" type="password" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} className="w-44" />
          <select className={selectCls} value={draft.network} onChange={(e) => setDraft({ ...draft, network: e.target.value })} disabled={draft.is_admin}>
            <option value="">— сеть —</option>
            {nets.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-sm text-ink-muted">
            <input type="checkbox" checked={draft.is_admin} onChange={(e) => setDraft({ ...draft, is_admin: e.target.checked })} />
            администратор
          </label>
          <Button disabled={draft.username.length < 2 || draft.password.length < 8 || create.isPending} onClick={() => create.mutate(draft)}>
            <Plus className="h-4 w-4" /> Создать
          </Button>
        </div>
        <Err e={create.error} />
      </Section>

      <Section title="Пользователи">
        <div className="space-y-2">
          {(users.data ?? []).map((u: PanelUser) => (
            <div key={u.username} className="flex flex-wrap items-center gap-2 rounded-lg border border-hairline bg-black/20 p-3">
              <span className="min-w-40 text-sm font-medium text-ink">{u.username}</span>
              {u.is_admin ? (
                <span className="rounded bg-brand/15 px-1.5 py-0.5 text-[11px] text-brand">все сети</span>
              ) : (
                <select className={`${selectCls} h-9`} value={u.network} onChange={(e) => setNet.mutate({ u: u.username, n: e.target.value })}>
                  <option value="">—</option>
                  {nets.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              )}
              {!u.is_admin && (
                <Button variant="danger" size="sm" className="ml-auto" onClick={() => remove.mutate(u.username)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          ))}
        </div>
        <Err e={setNet.error || remove.error} />
      </Section>
    </div>
  );
}

/* ──────────────────────────── Промпты ──────────────────────────── */
function PromptsTab() {
  const qc = useQueryClient();
  const [scope, setScope] = useState<{ scope: string; key: string } | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});

  // Первый доступный уровень выбираем сами: у не-админа глобального нет.
  const probe = useQuery({ queryKey: ["prompts", "probe"], queryFn: () => api.prompts("global", "") });
  const active = scope ?? { scope: "global", key: "" };
  const q = useQuery({
    queryKey: ["prompts", active.scope, active.key],
    queryFn: () => api.prompts(active.scope, active.key),
    enabled: Boolean(scope) || Boolean(probe.data),
  });

  const save = useMutation({
    mutationFn: api.savePrompt,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const scopes = q.data?.scopes ?? probe.data?.scopes ?? [];
  const items = q.data?.items ?? [];
  const editable = q.data?.editable ?? false;

  if (probe.isLoading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        {scopes.map((s) => {
          const on = s.scope === active.scope && s.scope_key === active.key;
          return (
            <button
              key={`${s.scope}:${s.scope_key}`}
              onClick={() => { setScope({ scope: s.scope, key: s.scope_key }); setEdits({}); }}
              className={`rounded-lg px-2.5 py-1.5 text-[12px] ring-1 transition ${on ? "bg-brand/15 text-brand ring-brand/40" : "bg-white/[0.03] text-ink-muted ring-hairline hover:bg-white/[0.07]"}`}
            >
              {s.title}
            </button>
          );
        })}
      </div>

      {q.isLoading && <Spinner />}

      {items.map((it) => {
        // Поле всегда предзаполнено: своим значением, а если его нет — тем,
        // что реально уходит в модель. Пустых полей в редакторе не бывает.
        const val = edits[it.key] ?? (it.value || it.effective);
        const dirty = val !== (it.value || it.effective);
        return (
          <Section key={it.key} title={it.title}>
            <textarea
              className="h-52 w-full resize-y rounded-lg border border-hairline bg-black/30 p-2.5 font-mono text-[12px] leading-relaxed text-ink outline-none focus:border-brand"
              value={val}
              disabled={!editable}
              onChange={(e) => setEdits({ ...edits, [it.key]: e.target.value })}
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                disabled={!editable || save.isPending || !dirty}
                onClick={() => save.mutate({ scope: active.scope, scope_key: active.key, key: it.key, text: val })}
              >
                <Check className="h-3.5 w-3.5" /> Сохранить
              </Button>
              <Button
                variant="subtle"
                size="sm"
                disabled={!editable || (!it.value && !edits[it.key])}
                onClick={() => {
                  setEdits((p) => { const n = { ...p }; delete n[it.key]; return n; });
                  save.mutate({ scope: active.scope, scope_key: active.key, key: it.key, text: "" });
                }}
              >
                <RotateCcw className="h-3.5 w-3.5" /> Сбросить
              </Button>
            </div>
          </Section>
        );
      })}
      <Err e={save.error} />
    </div>
  );
}

/* ──────────────────────────── Страница ──────────────────────────── */
export default function SettingsPage() {
  const { isAdmin } = useAuth();
  const [tab, setTab] = useState<Tab>(isAdmin ? "studios" : "prompts");

  const TABS: { id: Tab; label: string; icon: typeof Building2; adminOnly: boolean }[] = [
    { id: "studios", label: "Студии", icon: Building2, adminOnly: true },
    { id: "users", label: "Пользователи", icon: Users, adminOnly: true },
    { id: "prompts", label: "Промпты ИИ", icon: Bot, adminOnly: false },
  ];

  return (
    <AppShell title="Настройки">
      <div className="mx-auto w-full max-w-4xl space-y-4 p-4">
        <div className="flex gap-1.5">
          {TABS.filter((t) => isAdmin || !t.adminOnly).map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] ring-1 transition ${tab === t.id ? "bg-brand/15 text-brand ring-brand/40" : "bg-white/[0.03] text-ink-muted ring-hairline hover:bg-white/[0.07]"}`}
            >
              <t.icon className="h-4 w-4" /> {t.label}
            </button>
          ))}
        </div>

        {tab === "studios" && isAdmin && <StudiosTab />}
        {tab === "users" && isAdmin && <UsersTab />}
        {tab === "prompts" && <PromptsTab />}
      </div>
    </AppShell>
  );
}
