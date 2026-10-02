"use client";

import { useEffect, useState } from "react";
import { api, qs } from "@/lib/api";
import { fmtDate, toLocalInput } from "@/lib/format";
import type { Job, Page, Post } from "@/lib/types";
import { Alerts, Badge, Field, JobStatus, Modal, ProjectSelect, useAction, useJob, useLoad, useQueryParam } from "@/components/ui";

const STATUSES = ["", "draft", "approved", "scheduled", "publishing", "published", "failed"];

export default function ContentPage() {
  const [projectId, setProjectId, ready] = useQueryParam("project_id");
  const [postParam] = useQueryParam("post");
  const [status, setStatus] = useState("");
  const path = ready ? `/posts${qs({ project_id: projectId, status, limit: 100 })}` : null;
  const { data, reload, error } = useLoad<Page<Post>>(path, [projectId, status]);
  const action = useAction();
  const { job, start } = useJob(() => reload());
  const [open, setOpen] = useState<Post | null>(null);
  const [gen, setGen] = useState({ count: 1, topic: "", instructions: "" });

  useEffect(() => {
    if (postParam) api<Post>(`/posts/${postParam}`).then(setOpen).catch(() => undefined);
  }, [postParam]);

  return (
    <>
      <div className="topbar">
        <h1>Контент</h1>
        <div className="row">
          <ProjectSelect value={projectId} onChange={setProjectId} />
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 160 }}>{STATUSES.map((s) => <option key={s} value={s}>{s || "Все статусы"}</option>)}</select>
        </div>
      </div>
      <JobStatus job={job} />
      <Alerts error={error || action.error} message={action.message} />
      {projectId && (
        <div className="card row">
          <b>Сгенерировать:</b>
          <input type="number" min={1} max={20} value={gen.count} onChange={(e) => setGen({ ...gen, count: Number(e.target.value) })} style={{ width: 70 }} /> пост(ов)
          <input placeholder="Тема (необязательно — иначе из контент-плана)" value={gen.topic} onChange={(e) => setGen({ ...gen, topic: e.target.value })} style={{ flex: 1, minWidth: 200 }} />
          <input placeholder="Доп. указания" value={gen.instructions} onChange={(e) => setGen({ ...gen, instructions: e.target.value })} style={{ flex: 1, minWidth: 160 }} />
          <button className="primary" disabled={action.busy} onClick={async () => {
            const j = await action.run(() => api<Job>("/posts/generate", { method: "POST", json: { project_id: Number(projectId), count: gen.count, topic: gen.topic || null, instructions: gen.instructions || null } }));
            if (j) start(j);
          }}>Сгенерировать</button>
        </div>
      )}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>#</th><th>Пост</th><th>Рубрика</th><th>Статус</th><th>Время</th><th>Статистика</th><th /></tr></thead>
          <tbody>{(data?.items || []).map((p) => (
            <tr key={p.id}>
              <td>{p.id}</td>
              <td style={{ maxWidth: 420 }}>
                <a onClick={() => setOpen(p)} style={{ cursor: "pointer" }}><b>{p.title || p.text.slice(0, 60)}</b></a>
                <div className="small muted">{p.text.slice(0, 140)}…</div>
                {Boolean(p.generation_metadata?.similarity_warning) && <span className="badge warn">похож на прошлые</span>}
                {p.last_error && <div className="small" style={{ color: "var(--danger)" }}>{p.last_error}</div>}
              </td>
              <td><span className="badge info">{p.category || "—"}</span></td>
              <td><Badge value={p.status} />{p.attempts > 0 && <div className="small muted">попыток: {p.attempts}</div>}</td>
              <td className="small">{p.published_at ? `✓ ${fmtDate(p.published_at)}` : fmtDate(p.scheduled_at)}</td>
              <td className="small">{p.analytics?.views != null ? `👁 ${p.analytics.views} ❤ ${p.analytics.likes} 💬 ${p.analytics.comments} ↗ ${p.analytics.reposts}` : "—"}</td>
              <td><PostActions post={p} onDone={reload} action={action} /></td>
            </tr>))}
          </tbody>
        </table>
        {data && data.items.length === 0 && <p className="muted">Постов нет.</p>}
        {data && <div className="small muted">Всего: {data.total}</div>}
      </div>
      {open && <PostEditor post={open} onClose={() => setOpen(null)} onSaved={() => { reload(); }} />}
    </>
  );
}

function PostActions({ post, onDone, action }: { post: Post; onDone: () => void; action: ReturnType<typeof useAction> }) {
  const act = async (path: string, ok: string, method = "POST") => { await action.run(() => api(path, { method }), ok); onDone(); };
  return (
    <div className="row">
      {["draft", "approved"].includes(post.status) && <button className="small primary" onClick={() => act(`/posts/${post.id}/approve`, "Одобрено и поставлено в очередь")}>Одобрить</button>}
      {post.status === "scheduled" && <button className="small" onClick={() => act(`/posts/${post.id}/unschedule`, "Снято с очереди")}>Снять</button>}
      {post.status === "failed" && <button className="small" onClick={() => act(`/posts/${post.id}/retry`, "Поставлено на повтор")}>Повторить</button>}
      {["draft", "approved", "scheduled", "failed"].includes(post.status) && <button className="small" onClick={() => confirm("Опубликовать сейчас?") && act(`/posts/${post.id}/publish-now`, "Опубликовано")}>Сейчас</button>}
      {post.status !== "publishing" && <button className="small danger" onClick={() => confirm("Удалить пост из системы?") && act(`/posts/${post.id}`, "Удалён", "DELETE")}>✕</button>}
    </div>
  );
}

function PostEditor({ post, onClose, onSaved }: { post: Post; onClose: () => void; onSaved: () => void }) {
  const [p, setP] = useState(post);
  const [form, setForm] = useState({ title: post.title || "", text: post.text, image_prompt: post.image_prompt || "", image_format: post.image_format === "none" ? "square" : post.image_format });
  const [when, setWhen] = useState(toLocalInput(post.scheduled_at));
  const action = useAction();
  const editable = !["published", "publishing"].includes(p.status);
  const save = async () => {
    const updated = await action.run(() => api<Post>(`/posts/${p.id}`, { method: "PATCH", json: { title: form.title, text: form.text, image_prompt: form.image_prompt } }), "Сохранено");
    if (updated) { setP(updated); onSaved(); }
  };
  return (
    <Modal title={`Пост #${p.id}`} onClose={onClose}>
      <Alerts error={action.error} message={action.message} />
      <div className="row small" style={{ marginBottom: 8 }}><Badge value={p.status} /> рубрика: {p.category} {p.vk_post_id && <>· VK post {p.vk_post_id}</>}</div>
      <Field label="Заголовок"><input disabled={!editable} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
      <Field label="Текст"><textarea rows={12} disabled={!editable} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} /></Field>
      <div className="grid-2">
        <div>
          {p.image_url ? <img className="preview-img" src={p.image_url + `?v=${p.attachments.length}${p.image_format}`} alt="" /> : <p className="muted small">Без изображения</p>}
        </div>
        <div>
          <Field label="Промпт изображения"><textarea disabled={!editable} value={form.image_prompt} onChange={(e) => setForm({ ...form, image_prompt: e.target.value })} /></Field>
          <Field label="Формат"><select disabled={!editable} value={form.image_format} onChange={(e) => setForm({ ...form, image_format: e.target.value })}><option value="square">Квадрат</option><option value="vertical">Вертикальный</option><option value="horizontal">Горизонтальный</option></select></Field>
          {editable && <div className="row">
            <button disabled={action.busy} onClick={async () => { const u = await action.run(() => api<Post>(`/posts/${p.id}/image`, { method: "POST", json: { image_prompt: form.image_prompt, image_format: form.image_format } }), "Изображение сгенерировано"); if (u) { setP(u); onSaved(); } }}>{p.image_url ? "Перегенерировать" : "Сгенерировать"}</button>
            {p.image_url && <button className="danger" onClick={async () => { const u = await action.run(() => api<Post>(`/posts/${p.id}/image`, { method: "DELETE" })); if (u) { setP(u); onSaved(); } }}>Убрать</button>}
          </div>}
        </div>
      </div>
      {editable && (
        <div className="row" style={{ marginTop: 12 }}>
          <button className="primary" disabled={action.busy} onClick={save}>Сохранить</button>
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} style={{ width: 220 }} />
          <button disabled={!when} onClick={async () => { const u = await action.run(() => api<Post>(`/posts/${p.id}/schedule`, { method: "POST", json: { scheduled_at: new Date(when).toISOString() } }), "Запланировано"); if (u) { setP(u); onSaved(); } }}>Запланировать</button>
        </div>
      )}
      <details style={{ marginTop: 12 }}><summary className="small muted">Метаданные генерации</summary><pre className="json">{JSON.stringify(p.generation_metadata, null, 2)}</pre></details>
    </Modal>
  );
}
