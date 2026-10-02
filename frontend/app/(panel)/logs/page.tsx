"use client";

import { useState } from "react";
import { qs } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { AuditLog, Page, SystemLog } from "@/lib/types";
import { Alerts, Badge, useLoad } from "@/components/ui";

export default function LogsPage() {
  const [tab, setTab] = useState<"system" | "audit">("system");
  const [level, setLevel] = useState("");
  const [q, setQ] = useState("");
  const { data: system, error } = useLoad<Page<SystemLog>>(tab === "system" ? `/logs/system${qs({ level, q, limit: 200 })}` : null, [level, q, tab]);
  const { data: audit } = useLoad<Page<AuditLog>>(tab === "audit" ? "/logs/audit?limit=200" : null, [tab]);
  return (
    <>
      <h1>System Logs</h1>
      <div className="tabs">
        <button className={tab === "system" ? "active" : ""} onClick={() => setTab("system")}>Журнал ошибок и событий</button>
        <button className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}>Аудит действий</button>
      </div>
      <Alerts error={error} />
      {tab === "system" && (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <select value={level} onChange={(e) => setLevel(e.target.value)} style={{ width: 160 }}><option value="">Все уровни</option><option value="error">error</option><option value="warning">warning</option><option value="info">info</option></select>
            <input placeholder="Поиск" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} />
          </div>
          <div className="card table-wrap">
            <table>
              <thead><tr><th>Время</th><th>Уровень</th><th>Источник</th><th>Проект</th><th>Сообщение</th></tr></thead>
              <tbody>{(system?.items || []).map((l) => (
                <tr key={l.id}><td className="small">{fmtDate(l.created_at)}</td><td><Badge value={l.level} /></td><td>{l.source}</td><td>{l.project_id ?? "—"}</td><td className="small">{l.message}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}
      {tab === "audit" && (
        <div className="card table-wrap">
          <table>
            <thead><tr><th>Время</th><th>Пользователь</th><th>Действие</th><th>Объект</th><th>Детали</th><th>IP</th></tr></thead>
            <tbody>{(audit?.items || []).map((a) => (
              <tr key={a.id}><td className="small">{fmtDate(a.created_at)}</td><td>{a.user_id ?? "—"}</td><td>{a.action}</td><td>{a.entity_type} {a.entity_id}</td><td className="small"><code>{JSON.stringify(a.details)}</code></td><td className="small">{a.ip}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </>
  );
}
