"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate, fmtMoney } from "@/lib/format";
import { Alerts, Field, useAction, useLoad } from "@/components/ui";

interface Settings { values: Record<string, unknown>; editable: string[]; provider: string; openai_key_configured: boolean; operations: string[] }
interface Call { id: number; model: string; operation: string; agent: string | null; input_tokens: number; cached_tokens: number; output_tokens: number; images: number; estimated_cost: number; project_id: number | null; success: boolean; automatic: boolean; created_at: string }

const JSON_KEYS = ["AI_MODEL_OVERRIDES", "AI_PRICING_JSON", "IMAGE_PRICING_JSON"];

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
      }
      else if (typeof current === "boolean") values[key] = raw === "true";
      else if (typeof current === "number") values[key] = Number(raw);
      else values[key] = raw;
    }
    await action.run(() => api("/ai/settings", { method: "PUT", json: values }), "Настройки сохранены");
    reload();
  }

  if (!data) return <><h1>AI Settings</h1><Alerts error={error} /></>;
  return (
    <>
      <h1>AI Settings</h1>
      <Alerts error={action.error} message={action.message} />
      <div className="card small">
        Провайдер: <b>{data.provider}</b> · OPENAI_API_KEY: {data.openai_key_configured ? <span className="badge ok">задан в env</span> : <span className="badge err">не задан</span>}
        <div className="muted">Ключ задаётся только через переменные окружения. Ниже — параметры, которые можно менять без перезапуска и без изменения кода.</div>
      </div>
      <div className="card">
        <div className="form-grid">
          {data.editable.filter((k) => !JSON_KEYS.includes(k)).map((key) => {
            const current = data.values[key];
            return (
              <Field key={key} label={key}>
                {typeof current === "boolean" ? (
                  <select value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })}><option value="true">true</option><option value="false">false</option></select>
                ) : (
                  <input value={form[key] ?? ""} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
                )}
              </Field>
            );
          })}
        </div>
        {JSON_KEYS.map((key) => (
          <Field key={key} label={`${key} (JSON)${key === "AI_MODEL_OVERRIDES" ? " — операции: " + data.operations.join(", ") : ""}`}>
            <textarea rows={4} value={form[key] ?? "{}"} onChange={(e) => setForm({ ...form, [key]: e.target.value })} style={{ fontFamily: "monospace" }} />
          </Field>
        ))}
        <button className="primary" disabled={action.busy} onClick={save}>Сохранить</button>
      </div>
      <div className="card table-wrap">
        <h2>Последние AI-вызовы</h2>
        <table>
          <thead><tr><th>Время</th><th>Операция</th><th>Агент</th><th>Модель</th><th>In (cached)</th><th>Out</th><th>Стоимость</th><th>Проект</th><th>Авто</th></tr></thead>
          <tbody>{(calls || []).map((c) => (
            <tr key={c.id} style={{ opacity: c.success ? 1 : 0.6 }}>
              <td className="small">{fmtDate(c.created_at)}</td><td>{c.operation}</td><td className="small">{c.agent}</td><td className="small">{c.model}</td>
              <td>{c.input_tokens} ({c.cached_tokens})</td><td>{c.images ? `${c.images} img` : c.output_tokens}</td><td>{fmtMoney(c.estimated_cost)}</td><td>{c.project_id ?? "—"}</td><td>{c.automatic ? "да" : ""}</td>
            </tr>))}
          </tbody>
        </table>
      </div>
    </>
  );
}
