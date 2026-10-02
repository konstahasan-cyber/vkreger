"use client";

import Link from "next/link";
import { GOALS } from "@/lib/format";
import type { Project } from "@/lib/types";
import { Alerts, Badge, useLoad } from "@/components/ui";

export default function ProjectsPage() {
  const { data, error } = useLoad<Project[]>("/projects");
  return (
    <>
      <div className="topbar"><h1>Проекты</h1><Link href="/projects/new"><button className="primary">+ Новый проект</button></Link></div>
      <Alerts error={error} />
      <div className="card table-wrap">
        <table>
          <thead><tr><th>#</th><th>Проект</th><th>Цель</th><th>Статус</th><th>Сообщество</th><th>Частота</th><th>Автопилот</th></tr></thead>
          <tbody>
            {(data || []).map((p) => (
              <tr key={p.id}>
                <td>{p.id}</td>
                <td><Link href={`/projects/${p.id}`}><b>{p.name}</b></Link><div className="small muted">{p.business_name}{p.city ? `, ${p.city}` : ""}</div></td>
                <td>{GOALS[p.goal] || p.goal}</td>
                <td><Badge value={p.status} /></td>
                <td>{p.community_name || <span className="muted">не подключено</span>}</td>
                <td className="small">{p.posts_per_day ? `${p.posts_per_day}/день` : `${p.posts_per_week ?? "—"}/нед.`}</td>
                <td>{p.autopilot ? "вкл" : "выкл"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.length === 0 && <p className="muted">Проектов пока нет.</p>}
      </div>
    </>
  );
}
