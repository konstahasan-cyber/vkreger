"use client";

import { useState } from "react";
import { GOALS, TONES } from "@/lib/format";
import type { Account, Project } from "@/lib/types";
import { Field, useLoad } from "@/components/ui";

export type ProjectFormValues = Record<string, unknown>;

const EMPTY = {
  name: "", business_name: "", theme: "", niche: "", city: "", target_audience: "", product_description: "",
  advantages: "", website: "", contacts: "", goal: "leads", posts_per_day: "", posts_per_week: "7", tone: "friendly",
  custom_tone_prompt: "", vk_account_id: "", timezone: "Europe/Moscow", posting_times: "10:00, 19:00",
  autopilot: false, auto_approve: false, images_enabled: true, image_format: "square",
  auto_reply_mode: "APPROVAL", auto_reply_types: ["QUESTION"] as string[],
};

type State = typeof EMPTY;

function fromProject(p: Project): State {
  return {
    ...EMPTY,
    ...Object.fromEntries(Object.entries(p).map(([k, v]) => [k, v ?? ""])),
    posts_per_day: p.posts_per_day ? String(p.posts_per_day) : "",
    posts_per_week: p.posts_per_week ? String(p.posts_per_week) : "",
    vk_account_id: p.vk_account_id ? String(p.vk_account_id) : "",
    posting_times: (p.posting_times || []).join(", "),
    auto_reply_types: p.auto_reply_types || [],
  } as State;
}

export function toPayload(s: State): ProjectFormValues {
  const nullIfEmpty = (v: string) => (v.trim() === "" ? null : v.trim());
  return {
    ...s,
    theme: nullIfEmpty(s.theme), niche: nullIfEmpty(s.niche), city: nullIfEmpty(s.city),
    target_audience: nullIfEmpty(s.target_audience), product_description: nullIfEmpty(s.product_description),
    advantages: nullIfEmpty(s.advantages), website: nullIfEmpty(s.website), contacts: nullIfEmpty(s.contacts),
    custom_tone_prompt: nullIfEmpty(s.custom_tone_prompt),
    posts_per_day: s.posts_per_day ? Number(s.posts_per_day) : null,
    posts_per_week: s.posts_per_week ? Number(s.posts_per_week) : null,
    vk_account_id: s.vk_account_id ? Number(s.vk_account_id) : null,
    posting_times: s.posting_times.split(",").map((t) => t.trim()).filter(Boolean),
  };
}

export default function ProjectForm({ initial, submitLabel, busy, onSubmit }: {
  initial?: Project; submitLabel: string; busy?: boolean; onSubmit: (values: ProjectFormValues) => void;
}) {
  const [s, setS] = useState<State>(initial ? fromProject(initial) : EMPTY);
  const { data: accounts } = useLoad<Account[]>("/accounts");
  const set = (key: keyof State) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setS({ ...s, [key]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });
  const toggleType = (t: string) => setS({ ...s, auto_reply_types: s.auto_reply_types.includes(t) ? s.auto_reply_types.filter((x) => x !== t) : [...s.auto_reply_types, t] });

  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(toPayload(s)); }}>
      <div className="card">
        <h2>🏪 О бизнесе</h2>
        <p className="small muted">Эти данные AI использует для всех постов. Чем конкретнее (цены, адрес, фишки) — тем меньше «воды».</p>
        <div className="form-grid">
          <Field label="Название проекта *" hint="Для вас, в VK не публикуется"><input required value={s.name} onChange={set("name")} /></Field>
          <Field label="Название бизнеса *" hint="Как бизнес называется для клиентов"><input required value={s.business_name} onChange={set("business_name")} /></Field>
          <Field label="Тематика" hint="Например: кофейня, ремонт квартир"><input value={s.theme} onChange={set("theme")} /></Field>
          <Field label="Ниша" hint="Уточнение: specialty-кофе навынос"><input value={s.niche} onChange={set("niche")} /></Field>
          <Field label="Город / регион"><input value={s.city} onChange={set("city")} /></Field>
          <Field label="Сайт"><input value={s.website} onChange={set("website")} placeholder="https://" /></Field>
        </div>
        <Field label="Кто ваши клиенты" hint="Возраст, интересы, проблемы, которые вы решаете"><textarea value={s.target_audience} onChange={set("target_audience")} /></Field>
        <Field label="Что вы продаёте" hint="Товары/услуги, цены, условия"><textarea value={s.product_description} onChange={set("product_description")} /></Field>
        <Field label="Чем вы лучше конкурентов"><textarea value={s.advantages} onChange={set("advantages")} /></Field>
        <Field label="Контакты" hint="Телефон, адрес, мессенджеры — AI будет добавлять их в призывы"><input value={s.contacts} onChange={set("contacts")} /></Field>
      </div>
      <div className="card">
        <h2>📝 Посты</h2>
        <div className="form-grid">
          <Field label="Главная цель сообщества"><select value={s.goal} onChange={set("goal")}>{Object.entries(GOALS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Постов в день" hint="Если заполнено — важнее, чем «в неделю»"><input type="number" min={1} max={20} value={s.posts_per_day} onChange={set("posts_per_day")} /></Field>
          <Field label="Постов в неделю"><input type="number" min={1} max={100} value={s.posts_per_week} onChange={set("posts_per_week")} /></Field>
          <Field label="Стиль текстов"><select value={s.tone} onChange={set("tone")}>{Object.entries(TONES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Время публикаций" hint="Через запятую, например: 10:00, 19:00"><input value={s.posting_times} onChange={set("posting_times")} /></Field>
          <Field label="Часовой пояс" hint="Europe/Moscow, Asia/Yekaterinburg…"><input value={s.timezone} onChange={set("timezone")} /></Field>
          <Field label="Формат картинок"><select value={s.image_format} onChange={set("image_format")}><option value="square">Квадрат</option><option value="vertical">Вертикальный</option><option value="horizontal">Горизонтальный</option></select></Field>
          <Field label="Аккаунт VK" hint="От его имени публикуются посты"><select value={s.vk_account_id} onChange={set("vk_account_id")}><option value="">— не выбран —</option>{(accounts || []).map((a) => <option key={a.id} value={a.id}>{a.name} ({a.status})</option>)}</select></Field>
        </div>
        {s.tone === "custom" && <Field label="Опишите стиль своими словами" hint="Например: на «ты», с юмором, без канцелярита"><textarea value={s.custom_tone_prompt} onChange={set("custom_tone_prompt")} /></Field>}
        <div className="row">
          <label className="check"><input type="checkbox" checked={s.images_enabled} onChange={set("images_enabled")} /> Рисовать картинки к постам</label>
          <label className="check"><input type="checkbox" checked={s.autopilot} onChange={set("autopilot")} /> Автопилот: писать посты самому</label>
          <label className="check"><input type="checkbox" checked={s.auto_approve} onChange={set("auto_approve")} /> Публиковать без моей проверки</label>
        </div>
      </div>
      <div className="card">
        <h2>💬 Комментарии и сообщения</h2>
        <div className="form-grid">
          <Field label="Как отвечать"><select value={s.auto_reply_mode} onChange={set("auto_reply_mode")}>
            <option value="OFF">Только подсказка — AI предлагает ответ, отвечаю сам</option><option value="APPROVAL">С подтверждением — AI готовит, я нажимаю «Отправить»</option><option value="AUTO">Автоматически — AI отвечает сам на выбранные типы</option>
          </select></Field>
          <Field label="На что AI отвечает сам (в автоматическом режиме)">
            <div className="row">{["QUESTION", "LEAD", "OTHER"].map((t) => <label key={t} className="check"><input type="checkbox" checked={s.auto_reply_types.includes(t)} onChange={() => toggleType(t)} />{({ QUESTION: "Вопросы", LEAD: "Заявки", OTHER: "Прочее" } as Record<string, string>)[t]}</label>)}</div>
          </Field>
        </div>
        <p className="small muted">На негатив и спам AI никогда не отвечает сам. По заявкам AI только уточняет контакты, создаёт заявку и уведомляет вас.</p>
      </div>
      <button className="primary big" disabled={busy}>{busy ? "Сохранение…" : submitLabel}</button>
    </form>
  );
}
