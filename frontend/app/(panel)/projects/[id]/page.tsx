"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Account, Job, PlanItem, ProjectDetail, Rubric } from "@/lib/types";
import ProjectForm from "@/components/ProjectForm";
import { Alerts, Badge, Field, JobStatus, useAction, useJob, useLoad } from "@/components/ui";

interface Preview {
  name_options: string[]; description: string; status: string;
  design: { colors?: string[]; style?: string; avatar_prompt?: string; cover_prompt?: string };
  rubrics: { code: string; name: string; description: string }[];
  strategy: { positioning?: string; content_pillars?: string[]; rubric_mix?: { code: string; share: number }[]; best_times?: string[]; kpis?: string[] };
  pinned_post: { title?: string; text?: string };
  analysis: { business_summary?: string; audience_segments?: { name: string; pains: string[]; motives: string[] }[]; usp?: string[]; risks?: string[] };
}

const TABS = [["wizard", "Запуск"], ["settings", "Настройки"], ["rubrics", "Рубрики"], ["plan", "Контент-план"], ["strategy", "Стратегия"]] as const;

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const { data: project, reload, error } = useLoad<ProjectDetail>(`/projects/${id}`);
  const [tab, setTab] = useState<string>("wizard");
  const action = useAction();
  if (!project) return <><Alerts error={error} /><p className="muted">Загрузка…</p></>;

  return (
    <>
      <div className="topbar">
        <div>
          <h1 style={{ marginBottom: 4 }}>{project.name}</h1>
          <div className="row small muted"><Badge value={project.status} /> {project.business_name}
            {project.community_name && <> · сообщество: <b>{project.community_name}</b></>}</div>
        </div>
        <div className="row">
          <Link href={`/content?project_id=${project.id}`}><button>Контент</button></Link>
          <Link href={`/analytics?project_id=${project.id}`}><button>Аналитика</button></Link>
        </div>
      </div>
      <Alerts error={action.error} message={action.message} />
      <div className="tabs">{TABS.map(([key, label]) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>)}</div>
      {tab === "wizard" && <Wizard project={project} reload={reload} />}
      {tab === "settings" && (
        <ProjectForm initial={project} submitLabel="Сохранить" busy={action.busy} onSubmit={async (values) => {
          await action.run(() => api(`/projects/${project.id}`, { method: "PATCH", json: values }), "Сохранено");
          reload();
        }} />
      )}
      {tab === "rubrics" && <Rubrics project={project} reload={reload} />}
      {tab === "plan" && <Plan project={project} />}
      {tab === "strategy" && <Strategy project={project} />}
    </>
  );
}

function Wizard({ project, reload }: { project: ProjectDetail; reload: () => void }) {
  const action = useAction();
  const { job, start } = useJob(() => reload());
  const hasProposal = Object.keys(project.setup_proposal || {}).length > 0;

  return (
    <>
      <JobStatus job={job} />
      <Alerts error={action.error} message={action.message} />
      <div className="card">
        <h2>1. AI-анализ бизнеса</h2>
        <p className="muted">STRATEGIST анализирует бизнес и ЦА, предлагает название, описание, оформление, рубрики и стратегию — одним запросом.</p>
        <div className="row">
          <button className="primary" disabled={action.busy || job?.status === "running" || job?.status === "pending"}
            onClick={async () => { const j = await action.run(() => api<Job>(`/projects/${project.id}/setup`, { method: "POST", json: {} })); if (j) start(j); }}>
            {hasProposal ? "Перезапустить анализ" : "Запустить AI-анализ"}
          </button>
          {project.context_summary && <span className="small muted">Резюме: {project.context_summary}</span>}
        </div>
      </div>
      {hasProposal && !project.community_id && <CommunityStep project={project} reload={reload} />}
      {project.community_id && <RunStep project={project} reload={reload} />}
    </>
  );
}

function CommunityStep({ project, reload }: { project: ProjectDetail; reload: () => void }) {
  const { data: preview } = useLoad<Preview>(`/projects/${project.id}/preview`, [project.setup_proposal]);
  const { data: account } = useLoad<Account>(project.vk_account_id ? `/accounts/${project.vk_account_id}` : null);
  const action = useAction();
  const { job, start } = useJob(() => reload());
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("");
  const [pinned, setPinned] = useState({ title: "", text: "" });
  const [mode, setMode] = useState<"create" | "connect">("create");
  const [groupId, setGroupId] = useState("");
  const [communityToken, setCommunityToken] = useState("");

  useEffect(() => {
    if (!preview) return;
    setTitle(preview.name_options[0] || "");
    setDescription(preview.description);
    setStatus(preview.status);
    setPinned({ title: preview.pinned_post.title || "", text: preview.pinned_post.text || "" });
  }, [preview]);

  if (!preview) return <div className="card muted">Загрузка preview…</div>;
  if (!project.vk_account_id) return <div className="card"><h2>2. Сообщество</h2><div className="error-box">Выберите VK-аккаунт во вкладке «Настройки».</div></div>;

  const pinnedPayload = pinned.text ? pinned : null;
  return (
    <>
      <div className="card">
        <h2>2. Preview сообщества</h2>
        <div className="grid-2">
          <div>
            <Field label="Название (варианты от AI)">
              <select value={preview.name_options.includes(title) ? title : ""} onChange={(e) => setTitle(e.target.value)}>
                {preview.name_options.map((n) => <option key={n} value={n}>{n}</option>)}<option value="">свой вариант…</option>
              </select>
            </Field>
            <Field label="Название (до 48 символов)"><input maxLength={48} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
            <Field label="Статус (до 139 символов)"><input maxLength={139} value={status} onChange={(e) => setStatus(e.target.value)} /></Field>
            <Field label="Описание"><textarea rows={6} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
          </div>
          <div>
            <h3>Оформление</h3>
            <div className="row">{(preview.design.colors || []).map((c) => <span key={c} title={c} style={{ width: 28, height: 28, borderRadius: 6, background: c, border: "1px solid var(--border)", display: "inline-block" }} />)}</div>
            <p className="small">{preview.design.style}</p>
            <p className="small muted">Аватар: {preview.design.avatar_prompt}</p>
            <p className="small muted">Обложка: {preview.design.cover_prompt}</p>
            <h3>Анализ</h3>
            <p className="small">{preview.analysis.business_summary}</p>
            {(preview.analysis.audience_segments || []).map((s) => <div key={s.name} className="small"><b>{s.name}</b>: {s.pains.join("; ")}</div>)}
            <h3 style={{ marginTop: 8 }}>Рубрики</h3>
            <div className="row">{preview.rubrics.map((r) => <span key={r.code} className="badge info" title={r.description}>{r.code}</span>)}</div>
          </div>
        </div>
        <h3>Закреплённый пост</h3>
        <Field label="Заголовок"><input value={pinned.title} onChange={(e) => setPinned({ ...pinned, title: e.target.value })} /></Field>
        <Field label="Текст"><textarea rows={6} value={pinned.text} onChange={(e) => setPinned({ ...pinned, text: e.target.value })} /></Field>
      </div>
      <div className="card">
        <h2>3. Создать или подключить</h2>
        <JobStatus job={job} />
        <Alerts error={action.error} message={action.message} />
        <div className="row" style={{ marginBottom: 12 }}>
          <label className="row"><input type="radio" style={{ width: "auto" }} checked={mode === "create"} onChange={() => setMode("create")} /> Создать новое сообщество (groups.create)</label>
          <label className="row"><input type="radio" style={{ width: "auto" }} checked={mode === "connect"} onChange={() => setMode("connect")} /> Подключить существующее</label>
        </div>
        {mode === "connect" && (
          <div className="form-grid">
            <Field label="Сообщество аккаунта">
              <select value={groupId} onChange={(e) => setGroupId(e.target.value)}>
                <option value="">— выберите —</option>
                {(account?.groups_cache || []).map((g) => <option key={g.id} value={g.id}>{g.name} ({g.id})</option>)}
              </select>
            </Field>
            <Field label="Или ID сообщества"><input value={groupId} onChange={(e) => setGroupId(e.target.value.replace(/\D/g, ""))} /></Field>
            <Field label="Ключ доступа сообщества (для сообщений, необязательно)"><input value={communityToken} onChange={(e) => setCommunityToken(e.target.value)} /></Field>
          </div>
        )}
        <p className="small muted">После нажатия: заполнятся описание и статус, опубликуется и закрепится пост, будет создан контент-план и первая очередь публикаций (черновики для одобрения).</p>
        <button className="primary" disabled={action.busy || (mode === "connect" && !groupId) || (mode === "create" && !title)}
          onClick={async () => {
            const res = await action.run(() => mode === "create"
              ? api<{ job: Job }>(`/projects/${project.id}/community/create`, { method: "POST", json: { title, description, status, pinned_post: pinnedPayload, first_queue: true, queue_size: 3 } })
              : api<{ job: Job | null }>(`/projects/${project.id}/community/connect`, { method: "POST", json: { vk_group_id: Number(groupId), community_token: communityToken || null, apply_settings: true, description, status, pinned_post: pinnedPayload, first_queue: true, queue_size: 3 } }));
            if (res?.job) start(res.job); else if (res) reload();
          }}>
          {mode === "create" ? "Создать" : "Подключить"}
        </button>
      </div>
    </>
  );
}

function RunStep({ project, reload }: { project: ProjectDetail; reload: () => void }) {
  const action = useAction();
  const { job, start } = useJob(() => reload());
  const runJob = async (path: string, json?: unknown) => {
    const j = await action.run(() => api<Job>(path, { method: "POST", json }));
    if (j) start(j);
  };
  return (
    <div className="card">
      <h2>Сообщество подключено: {project.community_name}</h2>
      <JobStatus job={job} />
      <Alerts error={action.error} message={action.message} />
      <div className="row">
        <button onClick={() => runJob(`/projects/${project.id}/content-plan`, { days: 7 })}>Сгенерировать контент-план на неделю</button>
        <button onClick={() => runJob(`/projects/${project.id}/fill-queue?max_new=5`)}>Заполнить очередь</button>
        <button onClick={() => runJob(`/projects/${project.id}/analyst-review`)}>Ревизия стратегии (ANALYST)</button>
        <Link href={`/communities?id=${project.community_id}`}><button>События (комментарии/сообщения)</button></Link>
        <button className="danger" onClick={async () => { if (confirm("Отключить сообщество от проекта?")) { await action.run(() => api(`/projects/${project.id}/community/disconnect`, { method: "POST" })); reload(); } }}>Отключить</button>
      </div>
      <p className="small muted" style={{ marginTop: 12 }}>
        Автопилот: {project.autopilot ? "включён" : "выключен"} · одобрение: {project.auto_approve ? "автоматически" : "вручную"} · AUTO_REPLY: {project.auto_reply_mode}
      </p>
    </div>
  );
}

function Rubrics({ project, reload }: { project: ProjectDetail; reload: () => void }) {
  const action = useAction();
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const update = async (r: Rubric, patch: Partial<Rubric>) => { await action.run(() => api(`/projects/${project.id}/rubrics/${r.id}`, { method: "PATCH", json: patch })); reload(); };
  return (
    <div className="card table-wrap">
      <Alerts error={action.error} />
      <table>
        <thead><tr><th>Код</th><th>Название</th><th>Описание</th><th>Вес</th><th>Активна</th></tr></thead>
        <tbody>{project.rubrics.map((r) => (
          <tr key={r.id}>
            <td><code>{r.code}</code></td><td>{r.name}</td><td className="small">{r.description}</td>
            <td><input type="number" step="0.1" style={{ width: 80 }} defaultValue={r.weight} onBlur={(e) => update(r, { weight: Number(e.target.value) })} /></td>
            <td><input type="checkbox" style={{ width: "auto" }} checked={r.is_active} onChange={(e) => update(r, { is_active: e.target.checked })} /></td>
          </tr>))}
        </tbody>
      </table>
      <h3 style={{ marginTop: 16 }}>Добавить рубрику</h3>
      <div className="row">
        <input placeholder="code (latin)" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} style={{ width: 160 }} />
        <input placeholder="Название" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={{ width: 200 }} />
        <input placeholder="Описание" className="grow" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={{ flex: 1 }} />
        <button disabled={!form.code || !form.name} onClick={async () => { await action.run(() => api(`/projects/${project.id}/rubrics`, { method: "POST", json: form })); setForm({ code: "", name: "", description: "" }); reload(); }}>Добавить</button>
      </div>
    </div>
  );
}

function Plan({ project }: { project: ProjectDetail }) {
  const { data, reload } = useLoad<PlanItem[]>(`/projects/${project.id}/plan`);
  const action = useAction();
  const { job, start } = useJob(() => reload());
  const [days, setDays] = useState(7);
  return (
    <>
      <JobStatus job={job} />
      <Alerts error={action.error} message={action.message} />
      <div className="card row">
        <span>Сгенерировать план на</span>
        <input type="number" min={1} max={31} value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: 80 }} /> дней
        <button className="primary" disabled={action.busy} onClick={async () => { const j = await action.run(() => api<Job>(`/projects/${project.id}/content-plan`, { method: "POST", json: { days } })); if (j) start(j); }}>Сгенерировать</button>
      </div>
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Дата</th><th>Рубрика</th><th>Тема</th><th>Угол</th><th>Статус</th><th /></tr></thead>
          <tbody>{(data || []).map((item) => (
            <tr key={item.id}>
              <td className="small">{fmtDate(item.planned_for)}</td>
              <td><span className="badge info">{item.rubric_code}</span></td>
              <td>{item.topic}</td>
              <td className="small muted">{item.angle}</td>
              <td><Badge value={item.status} />{item.post_id && <Link href={`/content?post=${item.post_id}`} className="small"> пост #{item.post_id}</Link>}</td>
              <td><div className="row">
                {item.status === "planned" && <button className="small" onClick={async () => { const j = await action.run(() => api<Job>("/posts/generate", { method: "POST", json: { project_id: project.id, topic: item.topic, rubric_code: item.rubric_code, angle: item.angle } })); if (j) start(j); }}>Написать пост</button>}
                <button className="small danger" onClick={async () => { await action.run(() => api(`/projects/${project.id}/plan/${item.id}`, { method: "DELETE" })); reload(); }}>✕</button>
              </div></td>
            </tr>))}
          </tbody>
        </table>
        {data && data.length === 0 && <p className="muted">План пуст.</p>}
      </div>
    </>
  );
}

function Strategy({ project }: { project: ProjectDetail }) {
  const { data } = useLoad<{ id: number; version: number; is_active: boolean; source: string; data: Record<string, unknown>; reasoning: string | null; created_at: string }[]>(`/projects/${project.id}/strategies`);
  return (
    <>
      {(data || []).map((s) => (
        <div key={s.id} className="card">
          <div className="row"><h3 style={{ margin: 0 }}>Версия {s.version}</h3>{s.is_active && <span className="badge ok">активна</span>}<span className="badge info">{s.source}</span><span className="small muted">{fmtDate(s.created_at)}</span></div>
          {s.reasoning && <p>{s.reasoning}</p>}
          <pre className="json">{JSON.stringify(s.data, null, 2)}</pre>
        </div>
      ))}
      {data && data.length === 0 && <p className="muted">Стратегия появится после AI-анализа.</p>}
    </>
  );
}
