"use client";

import { api, qs } from "@/lib/api";
import type { Job } from "@/lib/types";
import { Alerts, JobStatus, ProjectSelect, useAction, useJob, useLoad, useQueryParam } from "@/components/ui";

interface Overview { project_id: number; name: string; posts: number; views: number; avg_views: number; avg_engagement_rate: number; clicks: number; leads: number; best_category: string | null }
interface Agg {
  posts_count: number; avg_views: number; avg_likes: number; avg_engagement_rate: number; total_views: number; total_clicks: number;
  by_category: { category: string; posts: number; avg_views: number; engagement_rate: number }[];
  best_hours: { hour: number; posts: number; engagement_rate: number; avg_views: number }[];
  top_posts: { id: number; title: string; category: string; views: number; er: number }[];
  worst_posts: { id: number; title: string; category: string; views: number; er: number }[];
  leads_count: number | null;
}

export default function AnalyticsPage() {
  const [projectId, setProjectId, ready] = useQueryParam("project_id");
  const { data: overview } = useLoad<Overview[]>("/analytics/overview");
  const { data: agg, reload } = useLoad<Agg>(ready && projectId ? `/analytics/projects/${projectId}${qs({ last_n: 30 })}` : null, [projectId]);
  const action = useAction();
  const { job, start } = useJob(() => reload());
  const maxEr = Math.max(1, ...(agg?.by_category || []).map((c) => c.engagement_rate));

  return (
    <>
      <div className="topbar">
        <h1>Аналитика</h1>
        <div className="row">
          <ProjectSelect value={projectId} onChange={setProjectId} />
          <button onClick={() => action.run(() => api("/analytics/collect", { method: "POST" }), "Сбор статистики из VK запущен")}>Собрать статистику</button>
          {projectId && <button onClick={async () => { const j = await action.run(() => api<Job>(`/projects/${projectId}/analyst-review`, { method: "POST" })); if (j) start(j); }}>AI-ревизия стратегии</button>}
        </div>
      </div>
      <Alerts error={action.error} message={action.message} />
      <JobStatus job={job} />
      {job?.status === "success" && <div className="card"><h3>Вывод ANALYST</h3><pre className="json">{JSON.stringify((job.result as { review?: unknown }).review ?? job.result, null, 2)}</pre></div>}
      {!projectId && (
        <div className="card table-wrap">
          <h2>Проекты за 30 дней</h2>
          <table>
            <thead><tr><th>Проект</th><th>Постов</th><th>Просмотры</th><th>Ср. просмотры</th><th>Ср. ER</th><th>Клики</th><th>Лиды</th><th>Лучшая рубрика</th></tr></thead>
            <tbody>{(overview || []).map((o) => (
              <tr key={o.project_id}><td><a style={{ cursor: "pointer" }} onClick={() => setProjectId(String(o.project_id))}>{o.name}</a></td><td>{o.posts}</td><td>{o.views}</td><td>{o.avg_views}</td><td>{o.avg_engagement_rate}%</td><td>{o.clicks}</td><td>{o.leads}</td><td>{o.best_category || "—"}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {projectId && agg && (
        <>
          <div className="grid">
            <div className="stat"><div className="label">Постов (последние 30)</div><div className="value">{agg.posts_count}</div></div>
            <div className="stat"><div className="label">Ср. просмотры</div><div className="value">{agg.avg_views}</div></div>
            <div className="stat"><div className="label">Ср. engagement</div><div className="value">{agg.avg_engagement_rate}%</div></div>
            <div className="stat"><div className="label">Клики</div><div className="value">{agg.total_clicks}</div></div>
            <div className="stat"><div className="label">Лиды</div><div className="value">{agg.leads_count ?? 0}</div></div>
          </div>
          <div className="grid-2" style={{ marginTop: 16 }}>
            <div className="card">
              <h3>Рубрики (ER)</h3>
              {agg.by_category.map((c) => (
                <div key={c.category} style={{ marginBottom: 8 }}>
                  <div className="row small"><b>{c.category}</b><span className="muted">{c.posts} пост., ср. просмотры {c.avg_views}</span><span style={{ marginLeft: "auto" }}>{c.engagement_rate}%</span></div>
                  <div className="bar" style={{ width: `${(c.engagement_rate / maxEr) * 100}%` }} />
                </div>
              ))}
            </div>
            <div className="card">
              <h3>Лучшее время</h3>
              <table><thead><tr><th>Час</th><th>Постов</th><th>ER</th><th>Просмотры</th></tr></thead>
                <tbody>{agg.best_hours.map((h) => <tr key={h.hour}><td>{h.hour}:00</td><td>{h.posts}</td><td>{h.engagement_rate}%</td><td>{h.avg_views}</td></tr>)}</tbody></table>
            </div>
            <div className="card">
              <h3>Лучшие публикации</h3>
              {agg.top_posts.map((p) => <div key={p.id} className="small">[{p.category}] {p.title} — ER {p.er}%, 👁 {p.views}</div>)}
            </div>
            <div className="card">
              <h3>Худшие публикации</h3>
              {agg.worst_posts.map((p) => <div key={p.id} className="small">[{p.category}] {p.title} — ER {p.er}%, 👁 {p.views}</div>)}
            </div>
          </div>
        </>
      )}
    </>
  );
}
