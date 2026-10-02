"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Community } from "@/lib/types";
import { Alerts, Field, Modal, useAction, useLoad } from "@/components/ui";

export default function CommunitiesPage() {
  const { data, reload, error } = useLoad<Community[]>("/communities");
  const { data: projects } = useLoad<{ id: number; name: string }[]>("/projects");
  const action = useAction();
  const [edit, setEdit] = useState<Community | null>(null);
  const [token, setToken] = useState("");
  const names = Object.fromEntries((projects || []).map((p) => [p.id, p.name]));
  const act = async (fn: () => Promise<unknown>, ok: string) => { await action.run(fn, ok); reload(); };

  return (
    <>
      <h1>Сообщества</h1>
      <Alerts error={error || action.error} message={action.message} />
      <div className="card small muted">
        Сообщества появляются здесь после «Обновить» у аккаунта или подключения в проекте. Для получения комментариев и сообщений
        включите Callback API (нужен публичный PUBLIC_BASE_URL) или Long Poll (нужен ключ доступа сообщества).
      </div>
      <div className="card table-wrap">
        <table>
          <thead><tr><th>VK ID</th><th>Название</th><th>Участники</th><th>Проект</th><th>Админ</th><th>События</th><th>Ключ сообщества</th><th>Синхр.</th><th /></tr></thead>
          <tbody>{(data || []).map((c) => (
            <tr key={c.id}>
              <td>{c.vk_group_id}</td>
              <td><a href={`https://vk.com/${c.screen_name || "club" + c.vk_group_id}`} target="_blank" rel="noreferrer">{c.name}</a>{c.created_by_app && <span className="badge info" style={{ marginLeft: 6 }}>создано</span>}{c.last_error && <div className="small muted">{c.last_error}</div>}</td>
              <td>{c.members_count ?? "—"}</td>
              <td>{c.project_id ? names[c.project_id] || `#${c.project_id}` : <span className="muted">—</span>}</td>
              <td>{c.is_admin ? "да" : "нет"}</td>
              <td>
                <select value={c.event_mode} onChange={(e) => act(() => api(`/communities/${c.id}/events`, { method: "POST", json: { mode: e.target.value } }), "События настроены")}>
                  <option value="none">выкл</option><option value="callback">Callback API</option><option value="longpoll">Long Poll</option>
                </select>
              </td>
              <td>{c.has_community_token ? <span className="badge ok">задан</span> : <span className="badge">нет</span>}</td>
              <td className="small">{fmtDate(c.last_synced_at)}</td>
              <td><div className="row">
                <button className="small" onClick={() => { setEdit(c); setToken(""); }}>Ключ</button>
                <button className="small" onClick={() => act(() => api(`/communities/${c.id}/sync`, { method: "POST" }), "Синхронизировано")}>Синхр.</button>
              </div></td>
            </tr>))}
          </tbody>
        </table>
        {data && data.length === 0 && <p className="muted">Сообществ нет.</p>}
      </div>
      {edit && (
        <Modal title={`Ключ доступа: ${edit.name}`} onClose={() => setEdit(null)}>
          <p className="small muted">Управление сообществом → Работа с API → Ключи доступа (права: сообщения, управление, фото, стена). Хранится зашифрованно.</p>
          <Field label="Ключ доступа сообщества"><input value={token} onChange={(e) => setToken(e.target.value)} /></Field>
          <div className="row">
            <button className="primary" disabled={!token} onClick={async () => { await act(() => api(`/communities/${edit.id}`, { method: "PATCH", json: { community_token: token } }), "Ключ сохранён"); setEdit(null); }}>Сохранить</button>
            {edit.has_community_token && <button className="danger" onClick={async () => { await act(() => api(`/communities/${edit.id}`, { method: "PATCH", json: { community_token: "" } }), "Ключ удалён"); setEdit(null); }}>Удалить ключ</button>}
          </div>
        </Modal>
      )}
    </>
  );
}
