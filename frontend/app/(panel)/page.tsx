"use client";

import Link from "next/link";
import { Alerts, useLoad } from "@/components/ui";
import { fmtMoney } from "@/lib/format";
import type { Account, Project } from "@/lib/types";

interface Dashboard {
  projects: { active: number; total: number; autopilot: number };
  accounts: { total: number; active: number; problems: number };
  proxies: { total: number; alive: number; dead: number; free: number };
  communities: { total: number; connected: number };
  posts: { published_today: number; scheduled_today: number; in_queue: number; awaiting_approval: number; failed: number };
  errors: { last_24h: number };
  leads: { new: number; last_7_days: number };
  inbox: { pending_approval: number };
  ai_costs: {
    today: number; last_7_days: number; last_30_days: number;
    by_project: { project_id: number | null; cost: number; calls: number }[];
    by_operation: { operation: string; cost: number; calls: number; input_tokens: number; output_tokens: number }[];
    limits: { spent_today: number; limit_day: number; global_exceeded: boolean };
  };
}

const OPS: Record<string, string> = {
  project_setup: "Анализ бизнеса", content_plan: "Контент-планы", post_compose: "Написание постов", post_edit: "Редактура",
  image_prompt: "Описания картинок", image_generate: "Картинки", analytics_review: "Аналитика", inbox_triage: "Разбор сообщений", embedding: "Проверка повторов",
};

function Stat({ icon, label, value, sub, href, alert }: { icon: string; label: string; value: React.ReactNode; sub?: React.ReactNode; href?: string; alert?: boolean }) {
  const body = (
    <div className="stat" style={alert ? { borderColor: "var(--danger)" } : undefined}>
      <div className="label">{icon} {label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
  return href ? <Link href={href} style={{ color: "inherit" }}>{body}</Link> : body;
}

export default function DashboardPage() {
  const { data, error } = useLoad<Dashboard>("/dashboard");
  const { data: projects } = useLoad<Project[]>("/projects");
  const { data: accounts } = useLoad<Account[]>("/accounts");
  const names = Object.fromEntries((projects || []).map((p) => [p.id, p.name]));
  if (!data) return <><h1>Главная</h1><Alerts error={error} /><p className="muted">Загрузка…</p></>;

  const firstProject = projects?.[0];
  const steps = [
    { done: (accounts || []).some((a) => a.status === "active"), label: "Добавить аккаунт VK", href: "/accounts", cta: "Добавить" },
    { done: (projects || []).length > 0, label: "Создать проект и описать бизнес", href: "/projects/new", cta: "Создать" },
    { done: (projects || []).some((p) => p.status !== "draft"), label: "Запустить AI-анализ бизнеса", href: firstProject ? `/projects/${firstProject.id}` : "/projects", cta: "Открыть проект" },
    { done: data.communities.connected > 0, label: "Подключить сообщество VK", href: firstProject ? `/projects/${firstProject.id}` : "/projects", cta: "Подключить" },
    { done: data.posts.in_queue > 0 || data.posts.published_today > 0 || (projects || []).some((p) => p.autopilot), label: "Проверить и одобрить первые посты", href: "/content?status=draft", cta: "К постам" },
  ];
  const allDone = steps.every((s) => s.done);
  const c = data.ai_costs;
  const pct = Math.min(100, (c.limits.spent_today / Math.max(c.limits.limit_day, 0.0001)) * 100);

  return (
    <>
      <h1>Главная</h1>
      <div className="page-sub">Сводка по всем сообществам и расходам на AI.</div>

      {!allDone && (
        <div className="card step-card">
          <h2>👋 С чего начать</h2>
          <ul className="checklist">
            {steps.map((s, i) => (
              <li key={s.label} className={s.done ? "done" : ""}>
                <span className="tick">{s.done ? "✓" : i + 1}</span>
                <span className="lbl">{s.label}</span>
                {!s.done && <Link href={s.href}><button className="small primary">{s.cta} →</button></Link>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(data.posts.awaiting_approval > 0 || data.inbox.pending_approval > 0 || data.leads.new > 0 || data.accounts.problems > 0 || data.posts.failed > 0) && (
        <div className="card">
          <h2>🔔 Требует внимания</h2>
          <div className="grid">
            {data.posts.awaiting_approval > 0 && <Stat icon="📝" label="Посты ждут проверки" value={data.posts.awaiting_approval} href="/content?status=draft" />}
            {data.inbox.pending_approval > 0 && <Stat icon="💬" label="Ответы ждут подтверждения" value={data.inbox.pending_approval} href="/messages" />}
            {data.leads.new > 0 && <Stat icon="🎯" label="Новые заявки" value={data.leads.new} href="/leads" />}
            {data.accounts.problems > 0 && <Stat icon="👤" label="Аккаунты с ошибкой" value={data.accounts.problems} href="/accounts" alert />}
            {data.posts.failed > 0 && <Stat icon="⚠️" label="Посты с ошибкой" value={data.posts.failed} href="/content?status=failed" alert />}
          </div>
        </div>
      )}

      <div className="grid" style={{ marginBottom: 16 }}>
        <Stat icon="🚀" label="Проекты в работе" value={data.projects.active} sub={`всего ${data.projects.total}, на автопилоте ${data.projects.autopilot}`} href="/projects" />
        <Stat icon="👥" label="Сообщества" value={data.communities.connected} sub={`подключено из ${data.communities.total}`} href="/communities" />
        <Stat icon="✅" label="Опубликовано сегодня" value={data.posts.published_today} sub={`ещё запланировано: ${data.posts.scheduled_today}`} href="/calendar" />
        <Stat icon="⏰" label="В очереди" value={data.posts.in_queue} href="/content?status=scheduled" />
        <Stat icon="👤" label="Аккаунты VK" value={`${data.accounts.active} из ${data.accounts.total}`} sub="работают" href="/accounts" />
        <Stat icon="🌐" label="Прокси" value={`${data.proxies.alive} из ${data.proxies.total}`} sub={`живые · свободных ${data.proxies.free}`} href="/proxies" />
        <Stat icon="🎯" label="Заявки за 7 дней" value={data.leads.last_7_days} href="/leads" />
        <Stat icon="🧾" label="Ошибки за сутки" value={data.errors.last_24h} href="/logs" alert={data.errors.last_24h > 0} />
      </div>

      <div className="card">
        <div className="card-head"><h2>🤖 Расходы на OpenAI</h2><Link href="/ai-settings" className="small">Лимиты и модели →</Link></div>
        <div className="grid" style={{ marginBottom: 14 }}>
          <Stat icon="📆" label="Сегодня" value={fmtMoney(c.today)} sub={`из лимита ${fmtMoney(c.limits.limit_day)}`} alert={c.limits.global_exceeded} />
          <Stat icon="🗓" label="За 7 дней" value={fmtMoney(c.last_7_days)} />
          <Stat icon="📅" label="За 30 дней" value={fmtMoney(c.last_30_days)} />
        </div>
        <div className="small muted">Дневной лимит {c.limits.global_exceeded ? "превышен — автоматические задачи на паузе до завтра" : `использован на ${pct.toFixed(0)}%`}</div>
        <div className="bar-bg" style={{ marginBottom: 16 }}><div className="bar" style={{ width: `${pct}%`, background: c.limits.global_exceeded ? "var(--danger)" : undefined }} /></div>
        <div className="grid-2">
          <div>
            <h3>По проектам (30 дней)</h3>
            {c.by_project.length === 0 ? <p className="muted small">Пока нет расходов</p> : (
              <table><tbody>{c.by_project.map((r) => <tr key={String(r.project_id)}><td>{r.project_id ? names[r.project_id] || `Проект #${r.project_id}` : "Без проекта"}</td><td className="muted small">{r.calls} запросов</td><td><b>{fmtMoney(r.cost)}</b></td></tr>)}</tbody></table>
            )}
          </div>
          <div>
            <h3>На что тратится (30 дней)</h3>
            {c.by_operation.length === 0 ? <p className="muted small">Пока нет расходов</p> : (
              <table><tbody>{c.by_operation.map((r) => <tr key={r.operation}><td>{OPS[r.operation] || r.operation}</td><td className="muted small">{r.calls} запросов</td><td><b>{fmtMoney(r.cost)}</b></td></tr>)}</tbody></table>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
