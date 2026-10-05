"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, qs } from "@/lib/api";
import { fmtDate, fmtDay, fmtTime, rubricLabel, toLocalInput } from "@/lib/format";
import type { Job, Page, Post } from "@/lib/types";
import { Alerts, Badge, Empty, Field, Hint, JobStatus, Modal, ProjectSelect, useAction, useJob, useLoad, useQueryParam } from "@/components/ui";

const FILTERS: [string, string][] = [
  ["draft", "📝 На проверке"],
  ["scheduled", "⏰ В очереди"],
  ["published", "✅ Опубликованные"],
  ["failed", "⚠️ С ошибкой"],
  ["", "Все"],
];

export default function ContentPage() {
  const [projectId, setProjectId, ready] = useQueryParam("project_id");
  const [statusParam, , statusReady] = useQueryParam("status");
  const [postParam] = useQueryParam("post");
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => { if (statusReady) setStatus(statusParam || "draft"); }, [statusReady, statusParam]);
  const path = ready && status !== null ? `/posts${qs({ project_id: projectId, status, limit: 60 })}` : null;
  const { data, reload, error } = useLoad<Page<Post>>(path, [projectId, status]);
  const action = useAction();
  const job = useJob((j) => { reload(); if (j.status === "success") action.setMessage("Посты написаны и добавлены во вкладку «На проверке»."); });
  const [open, setOpen] = useState<Post | null>(null);
  const [showGen, setShowGen] = useState(false);
  const [gen, setGen] = useState({ count: 1, topic: "", instructions: "", withImage: true });
  const { data: projectInfo } = useLoad<{ images_enabled: boolean }>(ready && projectId ? `/projects/${projectId}` : null, [projectId]);
  useEffect(() => { if (projectInfo) setGen((g) => ({ ...g, withImage: projectInfo.images_enabled })); }, [projectInfo]);

  useEffect(() => {
    if (postParam) api<Post>(`/posts/${postParam}`).then(setOpen).catch(() => undefined);
  }, [postParam]);

  const act = async (path: string, ok: string, method = "POST") => { await action.run(() => api(path, { method }), ok); reload(); };

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Посты</h1>
          <div className="page-sub">Проверяйте посты, которые написал AI, и одобряйте их — дальше они опубликуются сами по расписанию.</div>
        </div>
        <div className="row">
          <ProjectSelect value={projectId} onChange={setProjectId} />
          <button className="primary" disabled={!projectId} title={projectId ? "" : "Сначала выберите проект"} onClick={() => setShowGen(true)}>✨ Написать посты</button>
        </div>
      </div>
      <div className="tabs">{FILTERS.map(([key, label]) => <button key={key} className={status === key ? "active" : ""} onClick={() => setStatus(key)}>{label}</button>)}</div>
      <JobStatus job={job.job} hideSuccess />
      <Alerts error={error || action.error} message={action.message} />
      {status === "draft" && (data?.items.length ?? 0) > 0 && <Hint>Нажмите <b>«Одобрить»</b> — пост встанет в очередь и выйдет в указанное время. Чтобы поправить текст или картинку — <b>«Редактировать»</b>.</Hint>}

      {data && data.items.length === 0 ? (
        <div className="card">
          <Empty icon={status === "draft" ? "🎉" : "🗂"} title={status === "draft" ? "Нечего проверять" : "Здесь пока пусто"}>
            {projectId ? <button className="primary" onClick={() => setShowGen(true)}>✨ Написать посты</button> : <span>Выберите проект вверху или запустите его на странице <Link href="/projects">Проекты</Link>.</span>}
          </Empty>
        </div>
      ) : (
        <div className="grid-3">
          {(data?.items || []).map((p) => (
            <div key={p.id} className="post-card">
              <div className="ph">
                <span className="badge info">{rubricLabel(p.category)}</span>
                <Badge value={p.status} />
              </div>
              <div className="body">
                <div className="title">{p.title || p.topic}</div>
                <div className="text">{p.text}</div>
              </div>
              {p.image_url
                ? <img className={`img ${p.image_format}`} src={p.image_url} alt="" />
                : <div className="img-placeholder">{p.image_format === "none" ? "Без картинки" : "🖼 Картинки нет — её можно сгенерировать в «Редактировать»"}</div>}
              <div className="body" style={{ flex: "none", paddingTop: 8, paddingBottom: 8 }}>
                <div className="meta-line">
                  {p.published_at ? <span>✅ {fmtDay(p.published_at)} {fmtTime(p.published_at)}</span>
                    : p.scheduled_at ? <span>⏰ {fmtDay(p.scheduled_at)} {fmtTime(p.scheduled_at)}</span> : <span>время не назначено</span>}
                  {p.analytics?.views != null && <span>👁 {p.analytics.views} ❤ {p.analytics.likes} 💬 {p.analytics.comments}</span>}
                </div>
                {Boolean(p.generation_metadata?.similarity_warning) && <div className="small" style={{ color: "var(--warn)", marginTop: 4 }}>⚠️ Похож на прошлые посты — проверьте</div>}
                {p.last_error && <div className="small" style={{ color: "var(--danger)", marginTop: 4 }}>⚠️ {p.last_error}</div>}
              </div>
              <div className="foot">
                {["draft", "approved", "failed"].includes(p.status) && <button className="small primary" onClick={() => act(`/posts/${p.id}/approve`, "Одобрено: пост встал в очередь")}>✓ Одобрить</button>}
                {p.status !== "published" && p.status !== "publishing" && <button className="small" onClick={() => setOpen(p)}>✏️ Редактировать</button>}
                <button className="small" title="Создать такой же пост черновиком" onClick={async () => {
                  const c = await action.run(() => api<Post>(`/posts/${p.id}/duplicate`, { method: "POST" }));
                  if (c) { action.setMessage(`Копия создана (пост #${c.id}) — она во вкладке «На проверке»`); if (status === "draft") reload(); else setStatus("draft"); }
                }}>⧉ Копия</button>
                {p.status === "published" && <button className="small" onClick={() => setOpen(p)}>👁 Открыть</button>}
                {p.status === "scheduled" && <button className="small" onClick={() => act(`/posts/${p.id}/unschedule`, "Снято с очереди — пост снова на проверке")}>Снять с очереди</button>}
                {["draft", "approved", "scheduled", "failed"].includes(p.status) && <button className="small" onClick={() => confirm("Опубликовать этот пост в VK прямо сейчас?") && act(`/posts/${p.id}/publish-now`, "Опубликовано")}>🚀 Сейчас</button>}
                {p.status !== "publishing" && <button className="small ghost" title="Удалить" onClick={() => confirm(p.status === "published" ? "Удалить пост из панели? Из VK он не удалится." : "Удалить этот пост?") && act(`/posts/${p.id}`, "Удалено", "DELETE")}>🗑</button>}
              </div>
            </div>
          ))}
        </div>
      )}
      {data && data.total > data.items.length && <p className="small muted">Показано {data.items.length} из {data.total}</p>}

      {showGen && (
        <Modal title="Написать посты" onClose={() => setShowGen(false)}>
          <Field label="Сколько постов"><input type="number" min={1} max={20} value={gen.count} onChange={(e) => setGen({ ...gen, count: Number(e.target.value) })} /></Field>
          <Field label="Тема (необязательно)" hint="Если не указать — AI возьмёт следующие темы из контент-плана."><input value={gen.topic} onChange={(e) => setGen({ ...gen, topic: e.target.value })} placeholder="Например: как выбрать зерно для турки" /></Field>
          <Field label="Пожелания (необязательно)"><input value={gen.instructions} onChange={(e) => setGen({ ...gen, instructions: e.target.value })} placeholder="Например: упомянуть акцию −20% по будням" /></Field>
          <label className="check" style={{ marginBottom: 14 }}><input type="checkbox" checked={gen.withImage} onChange={(e) => setGen({ ...gen, withImage: e.target.checked })} /> 🖼 Рисовать картинки к этим постам</label>
          <button className="primary big" disabled={job.running} onClick={async () => {
            const j = await action.run(() => api<Job>("/posts/generate", { method: "POST", json: { project_id: Number(projectId), count: gen.count, topic: gen.topic || null, instructions: gen.instructions || null, with_image: gen.withImage } }));
            if (j) { job.start(j); setShowGen(false); setStatus("draft"); }
          }}>✨ Написать</button>
        </Modal>
      )}
      {open && <PostEditor post={open} onClose={() => setOpen(null)} onSaved={reload} />}
    </>
  );
}

function PostEditor({ post, onClose, onSaved }: { post: Post; onClose: () => void; onSaved: () => void }) {
  const [p, setP] = useState(post);
  const [form, setForm] = useState({ title: post.title || "", text: post.text, image_prompt: post.image_prompt || "", image_format: post.image_format === "none" ? "square" : post.image_format });
  const [when, setWhen] = useState(toLocalInput(post.scheduled_at));
  const action = useAction();
  const editable = !["published", "publishing"].includes(p.status);
  const apply = (u: Post | undefined) => { if (u) { setP(u); onSaved(); } };

  return (
    <Modal title={editable ? "Редактирование поста" : "Пост"} onClose={onClose}>
      <Alerts error={action.error} message={action.message} />
      <div className="row small" style={{ marginBottom: 12 }}><Badge value={p.status} /><span className="badge info">{rubricLabel(p.category)}</span>{p.vk_post_id && <span className="muted">пост VK №{p.vk_post_id}</span>}</div>
      <Field label="Заголовок (для вас, в VK публикуется только текст)"><input disabled={!editable} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
      <Field label="Текст поста"><textarea rows={12} disabled={!editable} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} /></Field>
      <div className="card soft">
        <h3>🖼 Картинка</h3>
        <div className="grid-2">
          <div>{p.image_url ? <img className="preview-img" src={`${p.image_url}?v=${encodeURIComponent(p.image_format + (p.attachments || []).length)}`} alt="" /> : <div className="img-placeholder">Картинки пока нет</div>}</div>
          <div>
            <Field label="Что нарисовать (описание для AI, можно по-русски)"><textarea disabled={!editable} value={form.image_prompt} onChange={(e) => setForm({ ...form, image_prompt: e.target.value })} /></Field>
            <Field label="Формат"><select disabled={!editable} value={form.image_format} onChange={(e) => setForm({ ...form, image_format: e.target.value })}><option value="square">Квадрат</option><option value="vertical">Вертикальная</option><option value="horizontal">Горизонтальная</option></select></Field>
            {editable && <div className="row">
              <button disabled={action.busy} onClick={async () => apply(await action.run(() => api<Post>(`/posts/${p.id}/image`, { method: "POST", json: { image_prompt: form.image_prompt, image_format: form.image_format } }), "Картинка готова"))}>{action.busy ? "Рисуем…" : p.image_url ? "🔄 Перерисовать" : "✨ Сгенерировать"}</button>
              {p.image_url && <button className="danger" onClick={async () => apply(await action.run(() => api<Post>(`/posts/${p.id}/image`, { method: "DELETE" }), "Картинка убрана"))}>Без картинки</button>}
            </div>}
          </div>
        </div>
      </div>
      {editable && (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <button className="primary" disabled={action.busy} onClick={async () => apply(await action.run(() => api<Post>(`/posts/${p.id}`, { method: "PATCH", json: { title: form.title, text: form.text, image_prompt: form.image_prompt } }), "Сохранено"))}>💾 Сохранить текст</button>
          </div>
          <div className="card soft">
            <h3>⏰ Когда опубликовать</h3>
            <div className="row">
              <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} style={{ width: 240 }} />
              <button disabled={!when} onClick={async () => apply(await action.run(() => api<Post>(`/posts/${p.id}/schedule`, { method: "POST", json: { scheduled_at: new Date(when).toISOString() } }), "Пост одобрен и запланирован"))}>Одобрить на это время</button>
            </div>
          </div>
        </>
      )}
      {p.published_at && <p className="small muted">Опубликован {fmtDate(p.published_at)}</p>}
      <button className="small" onClick={async () => {
        const c = await action.run(() => api<Post>(`/posts/${p.id}/duplicate`, { method: "POST" }), "Копия создана — она во вкладке «На проверке»");
        if (c) onSaved();
      }}>⧉ Создать копию поста</button>
      <details style={{ marginTop: 8 }}><summary className="small muted">Технические детали генерации</summary><pre className="json">{JSON.stringify(p.generation_metadata, null, 2)}</pre></details>
    </Modal>
  );
}
