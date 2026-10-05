"use client";

import { useState } from "react";
import { api, qs } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Lead, Page } from "@/lib/types";
import { Alerts, ProjectSelect, useAction, useLoad } from "@/components/ui";

const STATUSES = { new: "Новый", in_progress: "В работе", won: "Успех", lost: "Потерян" };

export default function LeadsPage() {
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState("");
  const { data, reload, error } = useLoad<Page<Lead>>(`/leads${qs({ project_id: projectId, status })}`, [projectId, status]);
  const { data: notifications, reload: reloadN } = useLoad<{ id: number; title: string; body: string; created_at: string; is_read: boolean }[]>("/notifications?unread=true");
  const action = useAction();
  const update = async (lead: Lead, patch: Partial<Lead>) => { await action.run(() => api(`/leads/${lead.id}`, { method: "PATCH", json: patch })); reload(); };

  return (
    <>
      <div className="topbar">
        <div><h1>Заявки</h1><div className="page-sub">Люди, которые захотели купить или записаться. AI собирает их из сообщений и комментариев.</div></div>
        <div className="row">
          <ProjectSelect value={projectId} onChange={setProjectId} />
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 150 }}><option value="">Все</option>{Object.entries(STATUSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </div>
      </div>
      <Alerts error={error || action.error} />
      {notifications && notifications.length > 0 && (
        <div className="card">
          <div className="topbar"><h3 style={{ margin: 0 }}>Новые уведомления ({notifications.length})</h3>
            <button className="small" onClick={async () => { await api("/notifications/read-all", { method: "POST" }); reloadN(); }}>Прочитано</button></div>
          {notifications.slice(0, 5).map((n) => <div key={n.id} className="small"><b>{n.title}</b> — {n.body} <span className="muted">{fmtDate(n.created_at)}</span></div>)}
        </div>
      )}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>#</th><th>Дата</th><th>Пользователь</th><th>Имя</th><th>Контакт</th><th>Что хочет</th><th>Статус</th><th>Заметки</th></tr></thead>
          <tbody>{(data?.items || []).map((l) => (
            <tr key={l.id}>
              <td>{l.id}</td>
              <td className="small">{fmtDate(l.created_at)}</td>
              <td>{l.vk_user_id ? <a href={`https://vk.com/id${l.vk_user_id}`} target="_blank" rel="noreferrer">id{l.vk_user_id}</a> : "—"}</td>
              <td><input defaultValue={l.name || ""} onBlur={(e) => e.target.value !== (l.name || "") && update(l, { name: e.target.value })} /></td>
              <td><input defaultValue={l.contact || ""} onBlur={(e) => e.target.value !== (l.contact || "") && update(l, { contact: e.target.value })} /></td>
              <td className="small" style={{ maxWidth: 260 }}>{l.need}</td>
              <td><select value={l.status} onChange={(e) => update(l, { status: e.target.value })}>{Object.entries(STATUSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></td>
              <td><input defaultValue={l.notes || ""} onBlur={(e) => e.target.value !== (l.notes || "") && update(l, { notes: e.target.value })} /></td>
            </tr>))}
          </tbody>
        </table>
        {data && data.items.length === 0 && <p className="muted">Заявок пока нет. Они появятся, когда в сообщество начнут писать (нужно включить приём сообщений на странице «Сообщества»).</p>}
      </div>
    </>
  );
}
