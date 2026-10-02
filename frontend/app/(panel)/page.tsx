"use client";

import Link from "next/link";
import { Alerts, useLoad } from "@/components/ui";
import { fmtMoney } from "@/lib/format";

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

function Stat({ label, value, sub, href }: { label: string; value: React.ReactNode; sub?: React.ReactNode; href?: string }) {
  const body = (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
  return href ? <Link href={href} style={{ color: "inherit" }}>{body}</Link> : body;
}

export default function DashboardPage() {
  const { data, error } = useLoad<Dashboard>("/dashboard");
  const { data: projects } = useLoad<{ id: number; name: string }[]>("/projects");
  const names = Object.fromEntries((projects || []).map((p) => [p.id, p.name]));
  if (!data) return <><h1>Dashboard</h1><Alerts error={error} /><p className="muted">Загрузка…</p></>;
  const c = data.ai_costs;
  const pct = Math.min(100, (c.limits.spent_today / Math.max(c.limits.limit_day, 0.0001)) * 100);
  return (
    <>
      <h1>Dashboard</h1>
      <div className="grid">
        <Stat label="Активные проекты" value={data.projects.active} sub={`всего ${data.projects.total}, автопилот ${data.projects.autopilot}`} href="/projects" />
        <Stat label="VK-аккаунты" value={`${data.accounts.active}/${data.accounts.total}`} sub={data.accounts.problems ? `проблем: ${data.accounts.problems}` : "все в порядке"} href="/accounts" />
        <Stat label="Proxy" value={`${data.proxies.alive}/${data.proxies.total}`} sub={`dead ${data.proxies.dead}, свободных ${data.proxies.free}`} href="/proxies" />
        <Stat label="Сообщества" value={data.communities.total} sub={`подключено к проектам: ${data.communities.connected}`} href="/communities" />
        <Stat label="Постов сегодня" value={data.posts.published_today} sub={`запланировано на сегодня: ${data.posts.scheduled_today}`} href="/calendar" />
        <Stat label="В очереди" value={data.posts.in_queue} sub={`ждут одобрения: ${data.posts.awaiting_approval}`} href="/content" />
        <Stat label="Ошибки (24ч)" value={data.errors.last_24h} sub={`постов с ошибкой: ${data.posts.failed}`} href="/logs" />
        <Stat label="Лиды" value={data.leads.new} sub={`за 7 дней: ${data.leads.last_7_days}`} href="/leads" />
        <Stat label="Ответы ждут оператора" value={data.inbox.pending_approval} href="/messages" />
      </div>

      <h2 style={{ marginTop: 24 }}>Затраты OpenAI</h2>
      <div className="grid">
        <Stat label="Сегодня" value={fmtMoney(c.today)} sub={`лимит ${fmtMoney(c.limits.limit_day)}${c.limits.global_exceeded ? " — ПРЕВЫШЕН" : ""}`} />
        <Stat label="7 дней" value={fmtMoney(c.last_7_days)} />
        <Stat label="30 дней" value={fmtMoney(c.last_30_days)} />
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <div className="small muted">Использование дневного лимита</div>
        <div style={{ background: "var(--border)", borderRadius: 4 }}><div className="bar" style={{ width: `${pct}%`, background: c.limits.global_exceeded ? "var(--danger)" : undefined }} /></div>
      </div>
      <div className="grid-2">
        <div className="card">
          <h3>По проектам (30 дней)</h3>
          <table><thead><tr><th>Проект</th><th>Вызовов</th><th>Стоимость</th></tr></thead>
            <tbody>{c.by_project.map((r) => <tr key={String(r.project_id)}><td>{r.project_id ? names[r.project_id] || `#${r.project_id}` : "без проекта"}</td><td>{r.calls}</td><td>{fmtMoney(r.cost)}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="card">
          <h3>По типам AI-операций (30 дней)</h3>
          <table><thead><tr><th>Операция</th><th>Вызовов</th><th>Токены in/out</th><th>Стоимость</th></tr></thead>
            <tbody>{c.by_operation.map((r) => <tr key={r.operation}><td>{r.operation}</td><td>{r.calls}</td><td>{r.input_tokens}/{r.output_tokens}</td><td>{fmtMoney(r.cost)}</td></tr>)}</tbody>
          </table>
        </div>
      </div>
    </>
  );
}
