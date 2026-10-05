"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate, fmtDay, GOALS, rubricLabel, TONES } from "@/lib/format";
import type { Account, Job, Page, PlanItem, ProjectDetail, Rubric } from "@/lib/types";
import ProjectForm from "@/components/ProjectForm";
import { BrandImport, DesignAssets } from "@/components/BrandPanel";
import { Alerts, Badge, Empty, Field, Hint, JobStatus, useAction, useJob, useLoad, useResumeJob } from "@/components/ui";

interface Preview {
  name_options: string[]; description: string; status: string;
  design: { colors?: string[]; style?: string; avatar_prompt?: string; cover_prompt?: string };
  rubrics: { code: string; name: string; description: string }[];
  strategy: { positioning?: string; content_pillars?: string[]; rubric_mix?: { code: string; share: number }[]; best_times?: string[]; kpis?: string[] };
  pinned_post: { title?: string; text?: string };
  analysis: { business_summary?: string; audience_segments?: { name: string; pains: string[]; motives: string[] }[]; usp?: string[]; risks?: string[] };
}

const TABS = [["launch", "🚀 Запуск"], ["style", "🎨 Стиль"], ["plan", "🗓 Контент-план"], ["rubrics", "🏷 Рубрики"], ["strategy", "🧭 Стратегия"], ["settings", "⚙️ Настройки"]] as const;
const PROJECT_STATUS: Record<string, string> = { draft: "Черновик", analyzing: "AI анализирует", proposal_ready: "Ждёт запуска", active: "Работает", paused: "На паузе", archived: "В архиве" };

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const { data: project, reload, error } = useLoad<ProjectDetail>(`/projects/${id}`);
  const { data: account } = useLoad<Account>(project?.vk_account_id ? `/accounts/${project.vk_account_id}` : null, [project?.vk_account_id]);
  const [tab, setTab] = useState<string>("launch");
  const action = useAction();
  if (!project) return <><Alerts error={error} /><p className="muted">Загрузка…</p></>;

  return (
    <>
      <div className="topbar">
        <div>
          <div className="small muted"><Link href="/projects">← Все проекты</Link></div>
          <h1>{project.name}</h1>
          <div className="row small muted">
            <Badge value={project.status === "active" ? "active" : project.status === "analyzing" ? "running" : "new"} label={PROJECT_STATUS[project.status] || project.status} />
            <span>{project.business_name}{project.city ? `, ${project.city}` : ""}</span>
            {project.community_name && <span>· сообщество «{project.community_name}»</span>}
          </div>
        </div>
        {project.community_id && (
          <div className="row">
            <Link href={`/content?project_id=${project.id}`}><button>📝 Посты</button></Link>
            <Link href={`/analytics?project_id=${project.id}`}><button>📊 Аналитика</button></Link>
          </div>
        )}
      </div>
      {!project.vk_account_id && !project.community_id && <Hint>Аккаунт VK не выбран — это нормально: сообщество можно подключить по <b>ключу доступа сообщества</b> (шаг «Сообщество VK»).</Hint>}
      {account && account.status !== "active" && (
        <Hint kind="warn">Аккаунт VK «{account.name}» не работает ({account.last_error || account.status}). Обновите токен на странице <Link href="/accounts">Аккаунты VK</Link> — иначе посты не будут публиковаться.</Hint>
      )}
      <Alerts error={action.error} message={action.message} />
      <div className="tabs">{TABS.map(([key, label]) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>)}</div>
      {tab === "launch" && <Launch project={project} account={account} reload={reload} />}
      {tab === "style" && <><div className="card"><BrandImport project={project} reload={reload} /></div><div className="card"><DesignAssets project={project} reload={reload} /></div></>}
      {tab === "plan" && <Plan project={project} />}
      {tab === "rubrics" && <Rubrics project={project} reload={reload} />}
      {tab === "strategy" && <Strategy project={project} />}
      {tab === "settings" && (
        <ProjectForm initial={project} submitLabel="Сохранить изменения" busy={action.busy} onSubmit={async (values) => {
          await action.run(() => api(`/projects/${project.id}`, { method: "PATCH", json: values }), "Сохранено");
          reload();
        }} />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ launch wizard */

function Steps({ current, done }: { current: number; done: number }) {
  const names = ["Анализ бизнеса", "Оформление", "Сообщество VK", "Посты", "Автопилот"];
  return (
    <div className="steps">
      {names.map((n, i) => {
        const cls = i < done ? "done" : i === current ? "current" : "";
        return <div key={n} className={`step-pill ${cls}`}><span className="num">{i < done ? "✓" : i + 1}</span>{n}</div>;
      })}
    </div>
  );
}

function Launch({ project, account, reload }: { project: ProjectDetail; account: Account | null; reload: () => void }) {
  const hasProposal = Object.keys(project.setup_proposal || {}).length > 0;
  const connected = Boolean(project.community_id);
  const [designOk, setDesignOk] = useState(false);
  const [draft, setDraft] = useState<{ title: string; description: string; status: string; pinned: { title: string; text: string } } | null>(null);
  const analysisJob = useJob(() => { setDesignOk(false); setDraft(null); reload(); });
  useResumeJob(project.id, ["project_setup"], analysisJob.start);

  const current = !hasProposal ? 0 : connected ? 3 : designOk ? 2 : 1;
  const done = connected ? 3 : designOk ? 2 : hasProposal ? 1 : 0;

  return (
    <>
      <Steps current={current} done={done} />
      <AnalysisStep project={project} hasProposal={hasProposal} job={analysisJob} reload={reload} />
      {hasProposal && !connected && (
        designOk && draft
          ? <DoneLine title="Оформление утверждено" detail={`Название: «${draft.title}»`} action="Изменить" onAction={() => setDesignOk(false)} />
          : <DesignStep project={project} initial={draft} reloadProject={reload} onConfirm={(d) => { setDraft(d); setDesignOk(true); }} />
      )}
      {hasProposal && !connected && designOk && draft && <CommunityStep project={project} account={account} draft={draft} reload={reload} />}
      {connected && <DoneLine title={`Сообщество подключено: «${project.community_name}»`} detail="Описание, статус и закреплённый пост заполняются автоматически при подключении." />}
      {connected && <div className="card step-card"><DesignAssets project={project} reload={reload} /></div>}
      {connected && <PostsStep project={project} reloadProject={reload} />}
      {connected && <AutopilotStep project={project} reload={reload} />}
    </>
  );
}

function DoneLine({ title, detail, action, onAction }: { title: string; detail?: string; action?: string; onAction?: () => void }) {
  return (
    <div className="card step-card done">
      <div className="done-line">
        <div className="t"><span className="tick">✓</span><div><b>{title}</b>{detail && <div className="small muted">{detail}</div>}</div></div>
        {action && <button className="small" onClick={onAction}>{action}</button>}
      </div>
    </div>
  );
}

function AnalysisStep({ project, hasProposal, job, reload }: { project: ProjectDetail; hasProposal: boolean; job: ReturnType<typeof useJob>; reload: () => void }) {
  const action = useAction();
  const [open, setOpen] = useState(false);
  const runAnalysis = async () => {
    const j = await action.run(() => api<Job>(`/projects/${project.id}/setup`, { method: "POST", json: {} }));
    if (j) job.start(j);
  };

  if (job.running) return <div className="card step-card"><h2>1. Анализ бизнеса</h2><JobStatus job={job.job} /></div>;

  if (hasProposal && !open) {
    return (
      <div className="card step-card done">
        <div className="done-line">
          <div className="t"><span className="tick">✓</span><div><b>AI проанализировал бизнес</b><div className="small muted">{project.context_summary}</div></div></div>
          <button className="small" onClick={() => setOpen(true)}>Подробнее</button>
        </div>
        <JobStatus job={job.job} hideSuccess />
      </div>
    );
  }

  return (
    <div className="card step-card">
      <div className="card-head"><h2>1. Анализ бизнеса</h2>{hasProposal && <button className="small" onClick={() => setOpen(false)}>Свернуть</button>}</div>
      <JobStatus job={job.job} hideSuccess />
      <Alerts error={action.error} />
      {!hasProposal ? (
        <>
          <p>AI изучит данные проекта (бизнес, город, аудиторию, продукт) и подготовит:</p>
          <ul className="muted" style={{ marginTop: 0 }}>
            <li>варианты названия, описание и статус сообщества;</li>
            <li>оформление (цвета, стиль) и закреплённый пост;</li>
            <li>рубрики и стратегию контента.</li>
          </ul>
          <details className="card soft" open={Boolean(project.website)} style={{ marginBottom: 14 }}>
            <summary><b>Есть сайт компании?</b> <span className="small muted">— необязательно, но так оформление и посты будут в вашем фирменном стиле</span></summary>
            <div style={{ marginTop: 10 }}><BrandImport project={project} reload={reload} compact /></div>
          </details>
          <p className="small muted">Чем подробнее заполнены поля во вкладке «Настройки», тем точнее результат.</p>
          <button className="primary big" disabled={action.busy} onClick={runAnalysis}>✨ Запустить AI-анализ</button>
        </>
      ) : (
        <>
          <p><b>Резюме:</b> {project.context_summary}</p>
          <p className="small muted">Если вы поменяли данные проекта, анализ можно запустить заново. Предложенные названия, описание, рубрики и стратегия будут перезаписаны.</p>
          <button disabled={action.busy} onClick={() => { if (confirm("Запустить анализ заново? Текущие предложения AI будут заменены новыми.")) runAnalysis(); }}>🔄 Запустить анализ заново</button>
        </>
      )}
    </div>
  );
}

function DesignStep({ project, initial, onConfirm, reloadProject }: {
  project: ProjectDetail; reloadProject: () => void;
  initial: { title: string; description: string; status: string; pinned: { title: string; text: string } } | null;
  onConfirm: (d: { title: string; description: string; status: string; pinned: { title: string; text: string } }) => void;
}) {
  const { data: preview } = useLoad<Preview>(`/projects/${project.id}/preview`, [project.setup_proposal]);
  const [title, setTitle] = useState(initial?.title || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [status, setStatus] = useState(initial?.status || "");
  const [pinned, setPinned] = useState(initial?.pinned || { title: "", text: "" });

  useEffect(() => {
    if (!preview || initial) return;
    setTitle(preview.name_options[0] || "");
    setDescription(preview.description);
    setStatus(preview.status);
    setPinned({ title: preview.pinned_post.title || "", text: preview.pinned_post.text || "" });
  }, [preview, initial]);

  if (!preview) return <div className="card muted">Загрузка предложений AI…</div>;
  return (
    <div className="card step-card">
      <h2>2. Оформление сообщества</h2>
      <p className="muted">Это предложения AI. Проверьте и при необходимости поправьте — именно это попадёт в сообщество VK.</p>
      <Field label="Название сообщества" hint="Нажмите на вариант AI или впишите своё (до 48 символов)">
        <div className="tag-list" style={{ marginBottom: 8 }}>
          {preview.name_options.map((n) => <button key={n} type="button" className={`small ${n === title ? "primary" : ""}`} onClick={() => setTitle(n)}>{n}</button>)}
        </div>
        <input maxLength={48} value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <div className="grid-2">
        <div>
          <Field label="Статус (строка под названием, до 139 символов)"><input maxLength={139} value={status} onChange={(e) => setStatus(e.target.value)} /></Field>
          <Field label="Описание сообщества"><textarea rows={7} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        </div>
        <div>
          <Field label="Закреплённый пост — заголовок"><input value={pinned.title} onChange={(e) => setPinned({ ...pinned, title: e.target.value })} /></Field>
          <Field label="Закреплённый пост — текст" hint="Опубликуется и закрепится вверху стены. Оставьте пустым, если не нужен."><textarea rows={7} value={pinned.text} onChange={(e) => setPinned({ ...pinned, text: e.target.value })} /></Field>
        </div>
      </div>
      <details className="card soft" style={{ marginBottom: 14 }}>
        <summary><b>Что ещё предложил AI</b> <span className="muted small">— анализ аудитории, стиль, рубрики</span></summary>
        <div className="grid-2" style={{ marginTop: 12 }}>
          <div>
            <h3>Аудитория</h3>
            <p className="small">{preview.analysis.business_summary}</p>
            {(preview.analysis.audience_segments || []).map((s) => <p key={s.name} className="small"><b>{s.name}:</b> {s.pains.join("; ")}</p>)}
          </div>
          <div>
            <h3>Стиль</h3>
            <div className="row" style={{ marginBottom: 6 }}>{(preview.design.colors || []).map((c) => <span key={c} className="swatch" title={c} style={{ background: c }} />)}</div>
            <p className="small">{preview.design.style}</p>
            <h3 style={{ marginTop: 10 }}>Рубрики</h3>
            <div className="tag-list">{preview.rubrics.map((r) => <span key={r.code} className="badge info" title={r.description}>{rubricLabel(r.code)}</span>)}</div>
          </div>
        </div>
      </details>
      <div className="card soft"><DesignAssets project={project} reload={reloadProject} /></div>
      <button className="primary big" disabled={!title.trim()} onClick={() => onConfirm({ title: title.trim(), description, status, pinned })}>Всё верно, дальше →</button>
    </div>
  );
}

function CommunityStep({ project, account, draft, reload }: {
  project: ProjectDetail; account: Account | null; reload: () => void;
  draft: { title: string; description: string; status: string; pinned: { title: string; text: string } };
}) {
  const action = useAction();
  const job = useJob(() => reload());
  useResumeJob(project.id, ["launch_community"], job.start);
  const [mode, setMode] = useState<"connect" | "create">("connect");
  const [groupId, setGroupId] = useState("");
  const [token, setToken] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [groups, setGroups] = useState(account?.groups_cache || []);
  useEffect(() => setGroups(account?.groups_cache || []), [account]);

  const noAccount = !project.vk_account_id;
  if (job.running) return <div className="card step-card"><h2>3. Сообщество VK</h2><JobStatus job={job.job} /><p className="small muted">Заполняем описание и статус, публикуем закреплённый пост, составляем контент-план и пишем первые посты…</p></div>;

  const pinned = draft.pinned.text ? draft.pinned : null;
  const submit = async () => {
    const body = mode === "create"
      ? { title: draft.title, description: draft.description, status: draft.status, pinned_post: pinned, first_queue: true, queue_size: 3 }
      : { vk_group_id: Number(groupId), community_token: token || null, apply_settings: true, description: draft.description, status: draft.status, pinned_post: pinned, first_queue: true, queue_size: 3 };
    const res = await action.run(() => api<{ job: Job | null }>(`/projects/${project.id}/community/${mode}`, { method: "POST", json: body }));
    if (res?.job) job.start(res.job); else if (res) reload();
  };
  const refreshGroups = async () => {
    setRefreshing(true);
    const acc = await action.run(() => api<Account>(`/accounts/${project.vk_account_id}/refresh`, { method: "POST" }));
    if (acc) setGroups(acc.groups_cache);
    setRefreshing(false);
  };

  return (
    <div className="card step-card">
      <h2>3. Сообщество VK</h2>
      <JobStatus job={job.job} hideSuccess />
      <Alerts error={action.error} />
      <div className="choices">
        <button type="button" className={`choice ${mode === "connect" ? "active" : ""}`} onClick={() => setMode("connect")}>
          <b>🔗 Подключить существующее</b><span className="small muted">Группа уже создана в VK, вы в ней администратор. Работает всегда.</span>
        </button>
        <button type="button" disabled={noAccount} className={`choice ${mode === "create" ? "active" : ""}`} onClick={() => setMode("create")}>
          <b>➕ Создать новое автоматически</b><span className="small muted">{noAccount ? "Нужен аккаунт VK (Standalone-приложение)." : "Требуется токен Standalone-приложения VK, иначе VK вернёт ошибку 15."}</span>
        </button>
      </div>
      {mode === "connect" ? (
        <>
          {noAccount ? (
            <Hint>
              <b>Как получить ключ сообщества</b> (без приложений и ИНН): откройте группу в VK → <b>Управление</b> → <b>Работа с API</b> → <b>Ключи доступа</b> →
              «Создать ключ» → отметьте <b>все права</b> (управление сообществом, сообщения, фотографии, стена, документы, истории) → «Создать».
              ID группы — число из адреса <code>vk.com/club123456</code> (или в «Управление → Основная информация»).
            </Hint>
          ) : <Hint>Создайте группу в VK вручную (Сообщества → Создать сообщество), затем нажмите «Обновить список» и выберите её. Можно также указать ключ сообщества — он надёжнее токена аккаунта.</Hint>}
          <div className="form-grid">
            {!noAccount && <Field label="Группа">
              <div className="row">
                <select value={groupId} onChange={(e) => setGroupId(e.target.value)} style={{ flex: 1 }}>
                  <option value="">— выберите группу —</option>
                  {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                </select>
                <button type="button" disabled={refreshing} onClick={refreshGroups}>{refreshing ? "…" : "🔄 Обновить список"}</button>
              </div>
            </Field>}
            <Field label={noAccount ? "ID группы" : "Или ID группы"} hint="Число из адреса vk.com/club123456"><input value={groupId} onChange={(e) => setGroupId(e.target.value.replace(/\D/g, ""))} /></Field>
          </div>
          <Field label={noAccount ? "Ключ доступа сообщества (обязательно)" : "Ключ доступа сообщества (рекомендуется)"} hint="С ним посты, картинки и ответы на сообщения работают без токена аккаунта: ключ не истекает и не зависит от IP.">
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="vk1.a…" />
          </Field>
        </>
      ) : (
        <p className="muted">Будет создана публичная страница «{draft.title}».</p>
      )}
      <Hint>После нажатия система сама: заполнит описание и статус, опубликует и закрепит пост, составит контент-план на неделю и напишет первые 3 поста (они придут как черновики — вы их проверите).</Hint>
      <button className="primary big" disabled={action.busy || (mode === "connect" && (!groupId || (noAccount && !token)))} onClick={submit}>
        {mode === "create" ? "🚀 Создать сообщество и запустить" : "🚀 Подключить и запустить"}
      </button>
    </div>
  );
}

function PostsStep({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const drafts = useLoad<Page<unknown>>(`/posts?project_id=${project.id}&status=draft&limit=1`);
  const queued = useLoad<Page<unknown>>(`/posts?project_id=${project.id}&status=scheduled&limit=1`);
  const published = useLoad<Page<unknown>>(`/posts?project_id=${project.id}&status=published&limit=1`);
  const action = useAction();
  const job = useJob((j) => {
    drafts.reload(); queued.reload();
    const r = j.result as { created?: number[]; skipped?: string | null };
    if (j.type === "fill_queue" && r.skipped === "queue is full") action.setMessage("Очередь уже заполнена на ближайшие дни — новые посты не нужны.");
    else if (j.type === "fill_queue" && r.created) action.setMessage(`Написано постов: ${r.created.length}. Проверьте их в разделе «Посты».`);
  });
  useResumeJob(project.id, ["generate_posts", "fill_queue", "launch_community"], job.start);
  const nDrafts = drafts.data?.total ?? 0;

  return (
    <div className="card step-card">
      <h2>4. Посты</h2>
      <JobStatus job={job.job} hideSuccess />
      <Alerts error={action.error} message={action.message} />
      <div className="grid" style={{ marginBottom: 14 }}>
        <div className="stat"><div className="label">📝 Ждут вашей проверки</div><div className="value">{nDrafts}</div></div>
        <div className="stat"><div className="label">⏰ В очереди на публикацию</div><div className="value">{queued.data?.total ?? 0}</div></div>
        <div className="stat"><div className="label">✅ Опубликовано</div><div className="value">{published.data?.total ?? 0}</div></div>
      </div>
      <div className="alert info" style={{ alignItems: "center" }}>
        🖼 <div style={{ flex: 1 }}>
          {project.images_enabled
            ? <>Картинки <b>включены</b>: к каждому новому посту AI рисует изображение ({project.image_format === "vertical" ? "вертикальное" : project.image_format === "horizontal" ? "горизонтальное" : "квадратное"}).</>
            : <>Картинки <b>выключены</b> — новые посты пишутся только текстом (дешевле и быстрее).</>}
        </div>
        <button className="small" disabled={action.busy} onClick={async () => {
          await action.run(() => api(`/projects/${project.id}`, { method: "PATCH", json: { images_enabled: !project.images_enabled } }),
            project.images_enabled ? "Картинки выключены" : "Картинки включены");
          reloadProject();
        }}>{project.images_enabled ? "Выключить картинки" : "Включить картинки"}</button>
      </div>
      <div className="row">
        <Link href={`/content?project_id=${project.id}&status=draft`}><button className="primary big">{nDrafts ? `👀 Проверить и одобрить посты (${nDrafts})` : "📝 Открыть посты"}</button></Link>
        <button disabled={action.busy || job.running} onClick={async () => {
          const j = await action.run(() => api<Job>(`/projects/${project.id}/fill-queue?max_new=5`, { method: "POST" }));
          if (j) job.start(j);
        }}>✨ Написать ещё посты на ближайшие дни</button>
      </div>
      <p className="small muted" style={{ marginTop: 10 }}>Одобренный пост встаёт в очередь и публикуется сам в запланированное время (время публикаций — во вкладке «Настройки»).</p>
    </div>
  );
}

function AutopilotStep({ project, reload }: { project: ProjectDetail; reload: () => void }) {
  const action = useAction();
  const set = async (patch: Record<string, unknown>, ok: string) => { await action.run(() => api(`/projects/${project.id}`, { method: "PATCH", json: patch }), ok); reload(); };
  return (
    <div className="card step-card">
      <h2>5. Автопилот</h2>
      <Alerts error={action.error} message={action.message} />
      <div className="grid-2">
        <div className="card soft">
          <label className="check"><input type="checkbox" checked={project.autopilot} onChange={(e) => set({ autopilot: e.target.checked }, e.target.checked ? "Автопилот включён" : "Автопилот выключен")} /><b>Автопилот</b></label>
          <p className="small muted" style={{ marginTop: 6 }}>Раз в час система проверяет очередь и сама пишет посты на {project.posts_per_day ? `${project.posts_per_day} в день` : `${project.posts_per_week ?? 7} в неделю`} на 3 дня вперёд.</p>
        </div>
        <div className="card soft">
          <label className="check"><input type="checkbox" checked={project.auto_approve} onChange={(e) => set({ auto_approve: e.target.checked }, "Сохранено")} /><b>Публиковать без моей проверки</b></label>
          <p className="small muted" style={{ marginTop: 6 }}>Если выключено — новые посты приходят черновиками и ждут вашего «Одобрить». Рекомендуем включать, когда качество устраивает.</p>
        </div>
        <div className="card soft">
          <b>💬 Комментарии и сообщения</b>
          <p className="small muted" style={{ marginTop: 6 }}>Режим ответов: <b>{project.auto_reply_mode === "OFF" ? "только подсказки" : project.auto_reply_mode === "AUTO" ? "автоматически" : "с подтверждением"}</b>. Чтобы получать сообщения, добавьте ключ сообщества и включите Long Poll.</p>
          <Link href="/communities"><button className="small">Настроить приём сообщений</button></Link>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ other tabs */

function Rubrics({ project, reload }: { project: ProjectDetail; reload: () => void }) {
  const action = useAction();
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const update = async (r: Rubric, patch: Partial<Rubric>) => { await action.run(() => api(`/projects/${project.id}/rubrics/${r.id}`, { method: "PATCH", json: patch })); reload(); };
  if (!project.rubrics.length) return <div className="card"><Empty icon="🏷" title="Рубрик пока нет">Они появятся после AI-анализа во вкладке «Запуск».</Empty></div>;
  return (
    <div className="card">
      <Hint>Рубрики — типы постов. Чем больше «вес», тем чаще AI пишет посты этой рубрики. Выключенная рубрика не используется.</Hint>
      <Alerts error={action.error} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>Рубрика</th><th>Описание</th><th>Вес</th><th>Включена</th></tr></thead>
          <tbody>{project.rubrics.map((r) => (
            <tr key={r.id}>
              <td><b>{r.name}</b><div className="small muted">{r.code}</div></td><td className="small">{r.description}</td>
              <td><input type="number" step="0.1" min="0" style={{ width: 80 }} defaultValue={r.weight} onBlur={(e) => update(r, { weight: Number(e.target.value) })} /></td>
              <td><input type="checkbox" checked={r.is_active} onChange={(e) => update(r, { is_active: e.target.checked })} /></td>
            </tr>))}
          </tbody>
        </table>
      </div>
      <h3 style={{ marginTop: 18 }}>Добавить свою рубрику</h3>
      <div className="row">
        <input placeholder="Код латиницей (promo)" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} style={{ width: 180 }} />
        <input placeholder="Название" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={{ width: 200 }} />
        <input placeholder="О чём посты этой рубрики" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={{ flex: 1, minWidth: 200 }} />
        <button disabled={!form.code || !form.name} onClick={async () => { await action.run(() => api(`/projects/${project.id}/rubrics`, { method: "POST", json: form })); setForm({ code: "", name: "", description: "" }); reload(); }}>Добавить</button>
      </div>
    </div>
  );
}

function Plan({ project }: { project: ProjectDetail }) {
  const { data, reload } = useLoad<PlanItem[]>(`/projects/${project.id}/plan`);
  const action = useAction();
  const job = useJob(() => reload());
  useResumeJob(project.id, ["content_plan", "generate_posts"], job.start);
  const [days, setDays] = useState(7);
  const planned = (data || []).filter((i) => i.status === "planned");
  const used = (data || []).filter((i) => i.status !== "planned");

  return (
    <>
      <Hint>
        Контент-план — это список <b>тем</b> на ближайшие дни. По каждой теме AI пишет готовый пост
        {project.images_enabled ? " с картинкой" : " (картинки выключены в настройках)"}. Новые посты появляются в разделе «Посты» как черновики.
      </Hint>
      <JobStatus job={job.job} />
      <Alerts error={action.error} message={action.message} />
      <div className="card row">
        <span>Составить план на</span>
        <input type="number" min={1} max={31} value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: 80 }} /> дней
        <button className="primary" disabled={action.busy || job.running || !project.rubrics.length} onClick={async () => { const j = await action.run(() => api<Job>(`/projects/${project.id}/content-plan`, { method: "POST", json: { days } })); if (j) job.start(j); }}>✨ Составить план</button>
        {!project.rubrics.length && <span className="small muted">Сначала запустите AI-анализ во вкладке «Запуск».</span>}
      </div>
      <div className="card">
        <div className="card-head"><h3>Ждут написания ({planned.length})</h3></div>
        {planned.length === 0 ? <Empty icon="🗓" title="Свободных тем нет">Составьте план — и AI предложит темы.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Когда</th><th>Рубрика</th><th>Тема</th><th /></tr></thead>
            <tbody>{planned.map((item) => (
              <tr key={item.id}>
                <td className="small" style={{ whiteSpace: "nowrap" }}>{fmtDay(item.planned_for)}</td>
                <td><span className="badge info">{rubricLabel(item.rubric_code)}</span></td>
                <td><b>{item.topic}</b>{item.angle && <div className="small muted">{item.angle}</div>}</td>
                <td><div className="row" style={{ flexWrap: "nowrap" }}>
                  <button className="small primary" disabled={job.running} onClick={async () => { const j = await action.run(() => api<Job>("/posts/generate", { method: "POST", json: { project_id: project.id, topic: item.topic, rubric_code: item.rubric_code, angle: item.angle } })); if (j) job.start(j); }}>✍️ Написать пост</button>
                  <button className="small ghost" title="Удалить тему" onClick={async () => { await action.run(() => api(`/projects/${project.id}/plan/${item.id}`, { method: "DELETE" })); reload(); }}>✕</button>
                </div></td>
              </tr>))}
            </tbody>
          </table></div>
        )}
      </div>
      {used.length > 0 && (
        <details className="card">
          <summary><b>Уже использованные темы ({used.length})</b></summary>
          <table style={{ marginTop: 10 }}><tbody>{used.map((item) => (
            <tr key={item.id}><td className="small">{fmtDay(item.planned_for)}</td><td><span className="badge">{rubricLabel(item.rubric_code)}</span></td><td>{item.topic}</td>
              <td>{item.post_id ? <Link className="small" href={`/content?post=${item.post_id}`}>Открыть пост →</Link> : <Badge value={item.status} />}</td></tr>
          ))}</tbody></table>
        </details>
      )}
    </>
  );
}

interface StrategyRow { id: number; version: number; is_active: boolean; source: string; data: { positioning?: string; content_pillars?: string[]; rubric_mix?: { code: string; share: number }[]; best_times?: string[]; kpis?: string[]; analyst_recommendations?: string[] }; reasoning: string | null; created_at: string }

function Strategy({ project }: { project: ProjectDetail }) {
  const { data } = useLoad<StrategyRow[]>(`/projects/${project.id}/strategies`);
  const active = (data || []).find((s) => s.is_active);
  if (data && !active) return <div className="card"><Empty icon="🧭" title="Стратегии пока нет">Она появится после AI-анализа во вкладке «Запуск».</Empty></div>;
  if (!active) return null;
  const d = active.data;
  const max = Math.max(1, ...(d.rubric_mix || []).map((m) => m.share));
  return (
    <>
      <div className="card">
        <div className="card-head"><h2>Текущая стратегия</h2><span className="small muted">версия {active.version} · {active.source === "analyst" ? "скорректирована AI-аналитиком" : active.source === "setup" ? "создана при анализе" : "ручная"} · {fmtDate(active.created_at)}</span></div>
        {d.positioning && <p><b>Позиционирование:</b> {d.positioning}</p>}
        {active.reasoning && <Hint>{active.reasoning}</Hint>}
        <div className="grid-2">
          <div>
            <h3>Доли рубрик</h3>
            {(d.rubric_mix || []).map((m) => (
              <div key={m.code} style={{ marginBottom: 8 }}>
                <div className="row between small"><span>{rubricLabel(m.code)}</span><span>{m.share}%</span></div>
                <div className="bar-bg"><div className="bar" style={{ width: `${(m.share / max) * 100}%` }} /></div>
              </div>
            ))}
          </div>
          <div>
            {d.content_pillars && <><h3>О чём пишем</h3><ul className="small" style={{ marginTop: 0 }}>{d.content_pillars.map((p) => <li key={p}>{p}</li>)}</ul></>}
            {d.best_times && <p className="small"><b>Лучшее время:</b> {d.best_times.join(", ")}</p>}
            {d.kpis && <p className="small"><b>Цели:</b> {d.kpis.join("; ")}</p>}
            {d.analyst_recommendations && <><h3>Рекомендации аналитика</h3><ul className="small">{d.analyst_recommendations.map((r) => <li key={r}>{r}</li>)}</ul></>}
          </div>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>Цель проекта: {GOALS[project.goal]} · тон: {TONES[project.tone]}</p>
      </div>
      {(data || []).length > 1 && (
        <details className="card"><summary><b>История версий ({data!.length})</b></summary>
          {data!.map((s) => <div key={s.id} className="small" style={{ marginTop: 8 }}>v{s.version} · {fmtDate(s.created_at)} · {s.reasoning || s.source}</div>)}
        </details>
      )}
    </>
  );
}
