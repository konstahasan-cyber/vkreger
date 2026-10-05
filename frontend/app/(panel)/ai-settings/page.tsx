"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate, fmtMoney } from "@/lib/format";
import { Alerts, Field, Hint, useAction, useLoad } from "@/components/ui";

interface Settings { values: Record<string, unknown>; editable: string[]; provider: string; openai_key_configured: boolean; openai_key_source: string | null; openai_key_hint: string | null; operations: string[] }

function OpenAIKey({ data, onSaved }: { data: Settings; onSaved: () => void }) {
  const action = useAction();
  const [key, setKey] = useState("");
  return (
    <div className="card step-card">
      <h2>🔑 Ключ OpenAI</h2>
      {data.openai_key_configured
        ? <p>Ключ подключён ✓ <span className="muted small">(заканчивается на {data.openai_key_hint}, {data.openai_key_source === "panel" ? "введён в панели" : "из файла .env"})</span></p>
        : <p className="muted">Ключ не задан — AI не сможет писать тексты.</p>}
      <p className="small muted">Возьмите ключ на <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">platform.openai.com/api-keys</a> → «Create new secret key» и вставьте сюда (Ctrl+V). Панель проверит его в OpenAI и сохранит зашифрованным.</p>
      <Alerts error={action.error} message={action.message} />
      <div className="row">
        <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-proj-…" style={{ flex: 1, minWidth: 260 }} />
        <button className="primary" disabled={action.busy || key.trim().length < 10} onClick={async () => {
          const r = await action.run(() => api("/ai/openai-key", { method: "PUT", json: { key } }), "Ключ проверен и сохранён ✓");
          if (r) { setKey(""); onSaved(); }
        }}>{action.busy ? "Проверяем…" : "Проверить и сохранить"}</button>
        {data.openai_key_source === "panel" && <button className="small ghost" onClick={async () => { await action.run(() => api("/ai/openai-key", { method: "PUT", json: { key: null } }), "Ключ из панели удалён"); onSaved(); }}>Удалить</button>}
      </div>
    </div>
  );
}
interface Call { id: number; model: string; operation: string; agent: string | null; input_tokens: number; cached_tokens: number; output_tokens: number; images: number; estimated_cost: number; project_id: number | null; success: boolean; automatic: boolean; created_at: string }

const JSON_KEYS = ["AI_MODEL_OVERRIDES", "AI_PRICING_JSON", "IMAGE_PRICING_JSON"];
const GROUPS: { title: string; keys: [string, string, string?][] }[] = [
  { title: "💰 Лимиты расходов (в долларах)", keys: [
    ["MAX_AI_COST_PER_DAY", "Максимум в сутки на всё", "При превышении автоматические задачи останавливаются до следующего дня"],
    ["MAX_AI_COST_PER_PROJECT_DAY", "Максимум в сутки на один проект"],
  ] },
  { title: "🧠 Модели", keys: [
    ["AI_DEFAULT_MODEL", "Основная модель для текстов", "Например gpt-5.4-mini (дешевле) или gpt-5.4 (умнее)"],
    ["AI_EMBEDDING_MODEL", "Модель для проверки повторов"],
    ["AI_EMBEDDINGS_ENABLED", "Проверять смысловые повторы постов"],
    ["AI_SEPARATE_EDITOR_PASS", "Отдельная редактура каждого поста", "Чуть лучше качество, примерно вдвое дороже"],
  ] },
  { title: "🖼 Картинки", keys: [
    ["IMAGE_PROVIDER", "Генератор картинок", "openai — включено, none — без картинок"],
    ["IMAGE_MODEL", "Модель картинок"],
    ["IMAGE_QUALITY", "Качество", "low / medium / high — чем выше, тем дороже"],
  ] },
  { title: "📝 Контент", keys: [
    ["SIMILARITY_THRESHOLD", "Порог похожести постов (0–1)", "Выше — строже к повторам смысла"],
    ["TITLE_SIMILARITY_THRESHOLD", "Порог похожести заголовков (0–1)"],
    ["QUEUE_HORIZON_DAYS", "На сколько дней вперёд автопилот готовит посты"],
    ["ANALYST_MIN_INTERVAL_DAYS", "Как часто AI пересматривает стратегию (дней)"],
    ["ANALYST_MIN_NEW_POSTS", "Минимум новых постов для пересмотра стратегии"],
  ] },
];
const OPS: Record<string, string> = {
  project_setup: "Анализ бизнеса", content_plan: "Контент-план", post_compose: "Пост", post_edit: "Редактура", image_prompt: "Описание картинки",
  image_generate: "Картинка", analytics_review: "Аналитика", inbox_triage: "Разбор сообщения", embedding: "Проверка повторов",
};

export default function AISettingsPage() {
  const { data, reload, error } = useLoad<Settings>("/ai/settings");
  const { data: calls } = useLoad<Call[]>("/ai/usage/calls?limit=50");
  const action = useAction();
  const [form, setForm] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!data) return;
    setForm(Object.fromEntries(Object.entries(data.values).map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v, null, 2) : String(v)])));
  }, [data]);

  async function save() {
    const values: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(form)) {
      const current = data!.values[key];
      if (JSON_KEYS.includes(key)) {
        try { values[key] = JSON.parse(raw || "{}"); } catch { action.setError(`${key}: некорректный JSON`); return; }
      } else if (typeof current === "boolean") values[key] = raw === "true";
      else if (typeof current === "number") values[key] = Number(raw);
      else values[key] = raw;
    }
    await action.run(() => api("/ai/settings", { method: "PUT", json: values }), "Настройки сохранены");
    reload();
  }

  if (!data) return <><h1>Настройки AI</h1><Alerts error={error} /></>;
  const input = (key: string) => typeof data.values[key] === "boolean"
    ? <select value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })}><option value="true">Да</option><option value="false">Нет</option></select>
    : <input value={form[key] ?? ""} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />;

  return (
    <>
      <h1>Настройки AI</h1>
      <div className="page-sub">Модели, лимиты расходов и качество контента. Изменения применяются сразу, без перезапуска.</div>
      {data.provider === "fake" && <Hint kind="warn">Включён демо-режим (AI_PROVIDER=fake): тексты ненастоящие. Для работы поставьте AI_PROVIDER=openai в файле .env.</Hint>}
      {data.provider !== "fake" && <OpenAIKey data={data} onSaved={reload} />}
      <Alerts error={action.error} message={action.message} />
      <div className="grid-2">
        {GROUPS.map((g) => (
          <div key={g.title} className="card">
            <h2>{g.title}</h2>
            {g.keys.filter(([k]) => k in data.values).map(([key, label, hint]) => <Field key={key} label={label} hint={hint}>{input(key)}</Field>)}
          </div>
        ))}
      </div>
      <details className="card">
        <summary><b>Для опытных: модели по операциям и цены</b></summary>
        <div style={{ marginTop: 12 }}>
          {JSON_KEYS.map((key) => (
            <Field key={key} label={key} hint={key === "AI_MODEL_OVERRIDES" ? `Операции: ${data.operations.join(", ")}. Пример: {"project_setup": "gpt-5.4"}` : "Цены в долларах за 1 млн токенов / за картинку"}>
              <textarea rows={4} value={form[key] ?? "{}"} onChange={(e) => setForm({ ...form, [key]: e.target.value })} style={{ fontFamily: "monospace" }} />
            </Field>
          ))}
        </div>
      </details>
      <button className="primary big" disabled={action.busy} onClick={save}>💾 Сохранить настройки</button>

      <div className="card table-wrap" style={{ marginTop: 20 }}>
        <h2>Последние запросы к AI</h2>
        <table>
          <thead><tr><th>Когда</th><th>Что делал</th><th>Модель</th><th>Токены (вход / выход)</th><th>Стоимость</th><th>Проект</th></tr></thead>
          <tbody>{(calls || []).map((c) => (
            <tr key={c.id} style={{ opacity: c.success ? 1 : 0.55 }}>
              <td className="small">{fmtDate(c.created_at)}</td>
              <td>{OPS[c.operation] || c.operation}{c.automatic && <span className="badge" style={{ marginLeft: 6 }}>авто</span>}{!c.success && <span className="badge err" style={{ marginLeft: 6 }}>ошибка</span>}</td>
              <td className="small muted">{c.model}</td>
              <td className="small">{c.images ? `${c.images} картинка` : `${c.input_tokens} / ${c.output_tokens}`}</td>
              <td>{fmtMoney(c.estimated_cost)}</td><td className="small">{c.project_id ?? "—"}</td>
            </tr>))}
          </tbody>
        </table>
      </div>
    </>
  );
}
