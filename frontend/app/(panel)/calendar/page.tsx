"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { qs } from "@/lib/api";
import { Badge, ProjectSelect, useLoad } from "@/components/ui";

interface Item { id: number; project_id: number; title: string; category: string | null; status: string; at: string }

function startOfWeek(d: Date) {
  const r = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  r.setDate(r.getDate() - ((r.getDay() + 6) % 7));
  return r;
}

export default function CalendarPage() {
  const [month, setMonth] = useState(() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1); });
  const [projectId, setProjectId] = useState("");
  const from = startOfWeek(month);
  const to = new Date(from);
  to.setDate(to.getDate() + 42);
  const { data } = useLoad<Item[]>(`/calendar${qs({ date_from: from.toISOString(), date_to: to.toISOString(), project_id: projectId })}`, [month, projectId]);
  const byDay = useMemo(() => {
    const map: Record<string, Item[]> = {};
    for (const item of data || []) {
      const key = new Date(item.at).toDateString();
      (map[key] ||= []).push(item);
    }
    return map;
  }, [data]);
  const days = Array.from({ length: 42 }, (_, i) => { const d = new Date(from); d.setDate(d.getDate() + i); return d; });
  const today = new Date().toDateString();

  return (
    <>
      <div className="topbar">
        <div><h1>Календарь</h1><div className="page-sub" style={{ textTransform: "capitalize" }}>{month.toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}</div></div>
        <div className="row">
          <ProjectSelect value={projectId} onChange={setProjectId} />
          <button onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>←</button>
          <button onClick={() => { const n = new Date(); setMonth(new Date(n.getFullYear(), n.getMonth(), 1)); }}>Сегодня</button>
          <button onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>→</button>
        </div>
      </div>
      <div className="calendar">
        {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((d) => <div key={d} className="small muted" style={{ textAlign: "center" }}>{d}</div>)}
        {days.map((d) => (
          <div key={d.toISOString()} className={`day ${d.toDateString() === today ? "today" : ""}`} style={{ opacity: d.getMonth() === month.getMonth() ? 1 : 0.5 }}>
            <b>{d.getDate()}</b>
            {(byDay[d.toDateString()] || []).map((item) => (
              <Link key={item.id} href={`/content?post=${item.id}`} style={{ color: "inherit" }}>
                <div className="item" title={item.title}>
                  {new Date(item.at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })} <Badge value={item.status} /> {item.title}
                </div>
              </Link>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}
