"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { fmtDay, fmtTime, rubricLabel } from "@/lib/format";
import type { Job, ProjectDetail } from "@/lib/types";
import { Alerts, Badge, Field, Hint, useAction, useJob, useLoad, useResumeJob } from "@/components/ui";

interface Item {
  post_id: number; status: string; published: boolean; published_at: string | null; scheduled_at: string | null;
  category: string | null; vk_post_id: number | null; has_image: boolean;
  old_title: string | null; old_text: string; new_title: string | null; new_text: string;
  include: boolean; retheme_status: "proposed" | "applied" | "failed"; error: string | null; edited: boolean;
}
interface Listing { items: Item[]; counts: { proposed: number; applied: number; failed: number } }

const EMPTY = { business_name: "", niche: "", city: "", target_audience: "", product_description: "", advantages: "", website: "", contacts: "" };

export default function RethemePage() {
  const { id } = useParams<{ id: string }>();
  const { data: project, reload: reloadProject } = useLoad<ProjectDetail>(`/projects/${id}`);
  const { data: listing, reload, setData } = useLoad<Listing>(`/projects/${id}/retheme`);
  const action = useAction();
  const [restart, setRestart] = useState(false);
  const [brief, setBrief] = useState(EMPTY);
  const [scope, setScope] = useState<"all" | "published">("all");
  const [keepImage, setKeepImage] = useState(true);
  const prepare = useJob((j) => {
    reload(); reloadProject(); setRestart(false);
    if (j.status === "success") {
      const r = j.result as { prepared: number; total: number; errors: string[] };
      if (r.errors?.length) action.setError(`Не все посты переписаны: ${r.errors.slice(0, 3).join("; ")}`);
      else action.setMessage(`Готово: ${r.prepared} новых текстов. Проверьте их ниже — в VK пока ничего не изменилось.`);
    }
  });
  const applyJob = useJob((j) => {
    reload();
    if (j.status === "success") {
      const r = j.result as { applied: number; failed: { post: number; error: string }[]; stopped: string | null };
      if (r.stopped) action.setError(`VK остановил замену: ${r.stopped}. Подождите и нажмите «Заменить» ещё раз — продолжится с оставшихся.`);
      else if (r.failed.length) action.setError(`Не заменено постов: ${r.failed.length}. Причина указана у каждого поста.`);
      action.setMessage(`Заменено постов: ${r.applied}`);
    }
  });
  useResumeJob(id, ["retheme_prepare"], prepare.start);
  useResumeJob(id, ["retheme_apply"], applyJob.start);

  const items = listing?.items || [];
  const pending = items.filter((i) => i.retheme_status !== "applied");
  const toApply = pending.filter((i) => i.include);
  const toVK = toApply.filter((i) => i.published).length;
  const busy = prepare.running || applyJob.running;
  const showForm = restart || (!busy && items.length === 0);
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setBrief({ ...brief, [k]: e.target.value });

  const patch = async (item: Item, body: Partial<{ text: string; include: boolean }>) => {
    const r = await action.run(() => api(`/posts/${item.post_id}/retheme`, { method: "PATCH", json: body }));
    if (r && listing) setData({ ...listing, items: listing.items.map((x) => x.post_id === item.post_id ? { ...x, new_text: body.text ?? x.new_text, include: body.include ?? x.include, edited: body.text ? true : x.edited } : x) });
  };

  const progress = (job: Job | null, label: string) => {
    if (!job || !(job.status === "pending" || job.status === "running")) return null;
    const r = job.result as { done?: number; total?: number };
    return <div className="alert info"><span className="spinner" /><div><b>{label}</b>{r.total ? ` — ${r.done} из ${r.total}` : " — AI анализирует новую тематику…"}. Можно уйти со страницы и вернуться.</div></div>;
  };

  return (
    <>
      <div className="topbar">
        <div>
          <div className="small muted"><Link href={`/projects/${id}`}>← {project?.name || "Проект"}</Link></div>
          <h1>Изменить тематику</h1>
          <div className="page-sub">AI перепишет посты сообщества под новый бизнес. Уже опубликованные посты меняются прямо в VK: дата, лайки и комментарии остаются. Аватар, обложка и название не трогаются.</div>
        </div>
      </div>
      <Alerts error={action.error} message={action.message} />
      {progress(prepare.job, "Пишем новые тексты")}
      {progress(applyJob.job, "Заменяем посты")}
      {prepare.job?.status === "failed" && <div className="alert err">⚠️ <div>{prepare.job.error}</div></div>}

      {showForm && (
        <div className="card">
          <h2>Новая тематика</h2>
          {project && <p className="small muted">Сейчас: <b>{project.business_name}</b>{project.niche ? ` · ${project.niche}` : ""}{project.product_description ? ` · ${project.product_description.slice(0, 120)}` : ""}</p>}
          <div className="form-grid">
            <Field label="Название бизнеса"><input value={brief.business_name} onChange={set("business_name")} placeholder="Агентство дизайна «Пиксель»" /></Field>
            <Field label="Ниша"><input value={brief.niche} onChange={set("niche")} placeholder="графический и веб-дизайн" /></Field>
            <Field label="Город / регион"><input value={brief.city} onChange={set("city")} placeholder="оставьте пустым, если не меняется" /></Field>
            <Field label="Сайт"><input value={brief.website} onChange={set("website")} placeholder="https://…" /></Field>
          </div>
          <Field label="Что предлагаете"><textarea rows={3} value={brief.product_description} onChange={set("product_description")} placeholder="логотипы, фирменный стиль, сайты под ключ, дизайн упаковки" /></Field>
          <div className="form-grid">
            <Field label="Для кого"><input value={brief.target_audience} onChange={set("target_audience")} placeholder="малый бизнес, стартапы, кафе и магазины" /></Field>
            <Field label="Преимущества"><input value={brief.advantages} onChange={set("advantages")} placeholder="3 варианта на выбор, правки без доплат" /></Field>
            <Field label="Контакты для CTA"><input value={brief.contacts} onChange={set("contacts")} placeholder="пишите в сообщения группы" /></Field>
          </div>
          <Field label="Какие посты переписать">
            <label className="check"><input type="radio" checked={scope === "all"} onChange={() => setScope("all")} /> Опубликованные и все, что в очереди и на проверке</label>
            <label className="check" style={{ marginTop: 6 }}><input type="radio" checked={scope === "published"} onChange={() => setScope("published")} /> Только опубликованные</label>
          </Field>
          <Hint>Сначала AI только <b>подготовит</b> новые тексты, а вы их посмотрите и поправите. В VK ничего не изменится, пока вы не нажмёте «Заменить». Новые посты после этого тоже будут писаться на новую тему.</Hint>
          <div className="row">
            <button className="primary big" disabled={busy || action.busy || !Object.values(brief).some((v) => v.trim())} onClick={async () => {
              const body = { scope, brief: Object.fromEntries(Object.entries(brief).filter(([, v]) => v.trim())) };
              const j = await action.run(() => api<Job>(`/projects/${id}/retheme`, { method: "POST", json: body }));
              if (j) { prepare.start(j); setData({ items: [], counts: { proposed: 0, applied: 0, failed: 0 } }); }
            }}>✨ Подготовить новые тексты</button>
            {restart && <button onClick={() => setRestart(false)}>Отмена</button>}
          </div>
        </div>
      )}

      {!showForm && items.length > 0 && (
        <>
          <div className="card">
            <div className="card-head">
              <h2>Новые тексты: {items.length}</h2>
              <div className="row">
                <button className="ghost" disabled={busy} onClick={() => setRestart(true)}>Начать заново</button>
                {pending.length > 0 && <button className="ghost" disabled={busy} onClick={async () => {
                  if (!confirm("Отменить все неприменённые новые тексты? Посты останутся как есть.")) return;
                  await action.run(() => api(`/projects/${id}/retheme`, { method: "DELETE" }), "Новые тексты отменены"); reload();
                }}>Отменить</button>}
              </div>
            </div>
            <div className="row small" style={{ marginBottom: 12 }}>
              <span className="badge info">ждут замены: {listing?.counts.proposed}</span>
              <span className="badge ok">заменено: {listing?.counts.applied}</span>
              {(listing?.counts.failed || 0) > 0 && <span className="badge err">не вышло: {listing?.counts.failed}</span>}
            </div>
            {pending.length > 0 && (
              <>
                <label className="check" style={{ marginBottom: 10 }}><input type="checkbox" checked={keepImage} onChange={(e) => setKeepImage(e.target.checked)} /> 🖼 Оставить старые картинки у постов (если снять — картинки уберутся, останется только текст)</label>
                <button className="primary big" disabled={busy || toApply.length === 0} onClick={async () => {
                  if (!confirm(`Заменить ${toApply.length} постов?${toVK ? ` Из них ${toVK} уже опубликованы — они изменятся прямо в VK.` : ""}`)) return;
                  const j = await action.run(() => api<Job>(`/projects/${id}/retheme/apply`, { method: "POST", json: { keep_image: keepImage } }));
                  if (j) applyJob.start(j);
                }}>🔄 Заменить {toApply.length} {toVK ? `(в VK — ${toVK})` : ""}</button>
                <p className="small muted" style={{ marginTop: 8 }}>Если VK не даст изменить какой-то пост, он будет помечен, остальные заменятся. Прежний текст каждого поста сохраняется — его можно вернуть в карточке поста.</p>
              </>
            )}
          </div>

          {items.map((item) => (
            <div key={item.post_id} className="card" style={{ opacity: item.include || item.retheme_status === "applied" ? 1 : 0.55 }}>
              <div className="row between" style={{ marginBottom: 10 }}>
                <div className="row small">
                  {item.published ? <span className="badge ok">✅ опубликован {fmtDay(item.published_at)} {fmtTime(item.published_at)}</span> : <Badge value={item.status} />}
                  <span className="badge info">{rubricLabel(item.category)}</span>
                  {item.retheme_status === "applied" && <span className="badge ok">✓ заменён</span>}
                  {item.retheme_status === "failed" && <span className="badge err">не заменён</span>}
                  {item.edited && <span className="badge">✏️ правлено вручную</span>}
                </div>
                {item.retheme_status !== "applied" && (
                  <label className="check"><input type="checkbox" checked={item.include} onChange={(e) => patch(item, { include: e.target.checked })} /> заменять</label>
                )}
              </div>
              {item.error && <div className="alert err small">⚠️ <div>{item.error}</div></div>}
              <div className="grid-2">
                <div>
                  <div className="small muted" style={{ marginBottom: 4 }}>Было</div>
                  <div className="small" style={{ whiteSpace: "pre-wrap", maxHeight: 260, overflow: "auto", background: "var(--soft, #f4f5fa)", borderRadius: 10, padding: 10 }}>{item.old_text}</div>
                </div>
                <div>
                  <div className="small muted" style={{ marginBottom: 4 }}>{item.retheme_status === "applied" ? "Стало" : "Станет (можно править)"}</div>
                  {item.retheme_status === "applied"
                    ? <div className="small" style={{ whiteSpace: "pre-wrap", maxHeight: 260, overflow: "auto", borderRadius: 10, padding: 10, border: "1px solid var(--border)" }}>{item.new_text}</div>
                    : <ProposalText item={item} onSave={(text) => patch(item, { text })} />}
                </div>
              </div>
            </div>
          ))}
        </>
      )}
    </>
  );
}

function ProposalText({ item, onSave }: { item: Item; onSave: (text: string) => void }) {
  const [text, setText] = useState(item.new_text);
  return (
    <>
      <textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} style={{ fontSize: 13 }} />
      {text !== item.new_text && <button className="small primary" onClick={() => onSave(text)}>💾 Сохранить правку</button>}
    </>
  );
}
