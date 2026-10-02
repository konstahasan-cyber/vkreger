"use client";

import { useState } from "react";
import { api, qs } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { InboxItem, Page } from "@/lib/types";
import { Alerts, Badge, ProjectSelect, useAction, useLoad } from "@/components/ui";

export default function MessagesPage() {
  const [projectId, setProjectId] = useState("");
  const [cls, setCls] = useState("");
  const [status, setStatus] = useState("pending_approval,suggested,new,failed");
  const { data, reload, error } = useLoad<Page<InboxItem>>(`/messages${qs({ project_id: projectId, classification: cls, reply_status: status })}`, [projectId, cls, status]);
  const action = useAction();
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const act = async (fn: () => Promise<unknown>, ok: string) => { await action.run(fn, ok); reload(); };

  return (
    <>
      <div className="topbar">
        <h1>Комментарии и сообщения</h1>
        <div className="row">
          <ProjectSelect value={projectId} onChange={setProjectId} />
          <select value={cls} onChange={(e) => setCls(e.target.value)} style={{ width: 140 }}>
            <option value="">Все типы</option>{["QUESTION", "LEAD", "NEGATIVE", "SPAM", "OTHER"].map((c) => <option key={c}>{c}</option>)}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 200 }}>
            <option value="pending_approval,suggested,new,failed">Требуют внимания</option>
            <option value="">Все</option><option value="sent">Отправленные</option><option value="ignored,rejected">Игнор/отклонённые</option>
          </select>
        </div>
      </div>
      <Alerts error={error || action.error} message={action.message} />
      {(data?.items || []).map((m) => (
        <div key={m.id} className="card">
          <div className="row small muted">
            <span className="badge">{m.kind === "comment" ? "комментарий" : "сообщение"}</span>
            <Badge value={m.classification || "new"} />
            {m.confidence != null && <span>уверенность {(m.confidence * 100).toFixed(0)}%</span>}
            <Badge value={m.reply_status} />
            <span>от <a href={`https://vk.com/id${m.from_id}`} target="_blank" rel="noreferrer">id{m.from_id}</a></span>
            <span>{fmtDate(m.created_at)}</span>
          </div>
          <p className="post-text">{m.text}</p>
          {m.error && <div className="error-box small">{m.error}</div>}
          {m.reply_status === "sent" ? (
            <div className="ok-box small">Ответ: {m.reply_text}</div>
          ) : (
            <>
              <textarea value={drafts[m.id] ?? m.suggested_reply ?? ""} onChange={(e) => setDrafts({ ...drafts, [m.id]: e.target.value })} placeholder="Ответ" />
              <div className="row" style={{ marginTop: 8 }}>
                <button className="primary small" disabled={action.busy || !(drafts[m.id] ?? m.suggested_reply)} onClick={() => act(() => api(`/messages/${m.id}/reply`, { method: "POST", json: { text: drafts[m.id] ?? m.suggested_reply } }), "Ответ отправлен")}>Отправить</button>
                <button className="small" onClick={() => act(() => api(`/messages/${m.id}/reject`, { method: "POST" }), "Отклонено")}>Отклонить</button>
                <button className="small" onClick={() => act(() => api(`/messages/${m.id}/triage`, { method: "POST" }), "Переклассифицировано")}>AI заново</button>
              </div>
            </>
          )}
        </div>
      ))}
      {data && data.items.length === 0 && <p className="muted">Нет сообщений.</p>}
    </>
  );
}
