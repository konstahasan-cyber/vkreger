"use client";

import Link from "next/link";
import { GOALS } from "@/lib/format";
import type { Project } from "@/lib/types";
import { Alerts, Badge, Empty, useLoad } from "@/components/ui";

const STATUS: Record<string, [string, string]> = {
  draft: ["new", "Нужен AI-анализ"], analyzing: ["running", "AI анализирует"], proposal_ready: ["new", "Нужно подключить сообщество"],
  active: ["active", "Работает"], paused: ["pending", "На паузе"], archived: ["", "Архив"],
};

export default function ProjectsPage() {
  const { data, error } = useLoad<Project[]>("/projects");
  return (
    <>
      <div className="topbar">
        <div><h1>Проекты</h1><div className="page-sub">Один проект — один бизнес и одно сообщество VK.</div></div>
        <Link href="/projects/new"><button className="primary big">+ Новый проект</button></Link>
      </div>
      <Alerts error={error} />
      {data && data.length === 0 && (
        <div className="card"><Empty icon="🚀" title="Проектов пока нет"><p>Создайте первый проект: опишите бизнес, а AI подготовит сообщество и посты.</p><Link href="/projects/new"><button className="primary">+ Создать проект</button></Link></Empty></div>
      )}
      <div className="grid-3">
        {(data || []).map((p) => {
          const [badge, label] = STATUS[p.status] || ["", p.status];
          return (
            <Link key={p.id} href={`/projects/${p.id}`} style={{ color: "inherit" }}>
              <div className="card" style={{ height: "100%", marginBottom: 0 }}>
                <div className="row between" style={{ marginBottom: 8 }}><Badge value={badge || "new"} label={label} />{p.autopilot && <span className="badge info">🤖 автопилот</span>}</div>
                <h2 style={{ marginBottom: 2 }}>{p.name}</h2>
                <div className="muted small" style={{ marginBottom: 10 }}>{p.business_name}{p.city ? `, ${p.city}` : ""}</div>
                <div className="meta-line">
                  <span>🎯 {GOALS[p.goal] || p.goal}</span>
                  <span>📝 {p.posts_per_day ? `${p.posts_per_day} в день` : `${p.posts_per_week ?? "—"} в неделю`}</span>
                  <span>👥 {p.community_name || "сообщество не подключено"}</span>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </>
  );
}
