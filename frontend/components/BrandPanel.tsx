"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Job, ProjectDetail } from "@/lib/types";
import { Alerts, Hint, JobStatus, useAction, useJob, useResumeJob } from "@/components/ui";

function assetUrl(projectId: number, kind: "avatar" | "cover", version: number) {
  return `/media/${projectId}/${kind}.png?v=${version}`;
}

/** Import of the company style from a website URL or an HTML file. */
export function BrandImport({ project, reload, compact }: { project: ProjectDetail; reload: () => void; compact?: boolean }) {
  const action = useAction();
  const job = useJob((j) => { if (j.status === "success") reload(); });
  useResumeJob(project.id, ["brand_import"], job.start);
  const [url, setUrl] = useState(project.website || "");
  const fileRef = useRef<HTMLInputElement>(null);
  const style = project.brand?.style;

  const fromUrl = async () => {
    const j = await action.run(() => api<Job>(`/projects/${project.id}/brand/import`, { method: "POST", json: { url } }));
    if (j) job.start(j);
  };
  const fromFile = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const j = await action.run(() => api<Job>(`/projects/${project.id}/brand/upload`, { method: "POST", body: form }));
    if (j) job.start(j);
  };

  return (
    <div>
      {!compact && <h3>🌐 Стиль с сайта компании</h3>}
      <p className="small muted">AI изучит сайт: цвета, шрифты, тон текстов, факты о товарах и ценах. По ним будут оформлены аватар, обложка, картинки и тексты постов.</p>
      <JobStatus job={job.job} hideSuccess />
      <Alerts error={action.error} />
      <div className="row" style={{ marginBottom: 8 }}>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://ваш-сайт.ру" style={{ flex: 1, minWidth: 220 }} />
        <button className="primary" disabled={action.busy || job.running || url.trim().length < 4} onClick={fromUrl}>🔍 Анализировать сайт</button>
        <button disabled={action.busy || job.running} onClick={() => fileRef.current?.click()}>📄 Загрузить HTML-файл</button>
        <input ref={fileRef} type="file" accept=".html,.htm,text/html" style={{ display: "none" }} onChange={(e) => { const f = e.target.files?.[0]; if (f) fromFile(f); e.target.value = ""; }} />
      </div>
      <p className="small muted">Если сайт не открывается (защита от ботов), сохраните страницу в браузере: Ctrl+S → «Веб-страница, только HTML» и загрузите файл.</p>
      {style && <StyleSummary style={style} />}
    </div>
  );
}

function StyleSummary({ style }: { style: NonNullable<ProjectDetail["brand"]["style"]> }) {
  return (
    <div className="card soft" style={{ marginTop: 10, marginBottom: 0 }}>
      <div className="row between"><b>✓ Фирменный стиль определён</b><span className="small muted">источник: {style.source}</span></div>
      {style.summary && <p className="small" style={{ marginTop: 6 }}>{style.summary}</p>}
      <div className="row" style={{ margin: "8px 0" }}>
        {(style.palette || []).map((c) => <span key={c} className="swatch" title={c} style={{ background: c }} />)}
        {(style.fonts || []).length > 0 && <span className="small muted">шрифты: {style.fonts!.join(", ")}</span>}
      </div>
      {style.visual_style && <p className="small"><b>Визуал:</b> {style.visual_style}</p>}
      {style.tone_of_voice && <p className="small"><b>Тон текстов:</b> {style.tone_of_voice}</p>}
      {(style.key_phrases || []).length > 0 && <p className="small"><b>Фирменные фразы:</b> {style.key_phrases!.join(" · ")}</p>}
    </div>
  );
}

/** Avatar & cover: preview, (re)generate, upload to VK. */
export function DesignAssets({ project, reload }: { project: ProjectDetail; reload: () => void }) {
  const action = useAction();
  const job = useJob((j) => {
    reload();
    const up = (j.result as { upload?: Record<string, string> }).upload;
    if (up) {
      const bad = Object.entries(up).filter(([, v]) => v !== "ok");
      if (bad.length) action.setError(bad.map(([k, v]) => `${k === "avatar" ? "Аватар" : "Обложка"}: ${v}`).join("\n"));
      else action.setMessage("Аватар и обложка загружены в сообщество VK");
    }
  });
  useResumeJob(project.id, ["design_generate"], job.start);
  const { avatar, cover } = project.brand || {};
  const connected = Boolean(project.community_id);
  const generate = async (kinds: string[]) => {
    const j = await action.run(() => api<Job>(`/projects/${project.id}/design/generate`, { method: "POST", json: { kinds, upload: connected } }));
    if (j) job.start(j);
  };
  const notUploaded = connected && [avatar, cover].some((a) => a && a.uploaded_version !== a.version);

  return (
    <div>
      <h3>🎨 Аватар и обложка сообщества</h3>
      <p className="small muted">AI нарисует их в фирменных цветах{project.brand?.style ? " с сайта" : ""}. {connected ? "После генерации они сразу загрузятся в сообщество." : "В VK они загрузятся автоматически при подключении сообщества."}</p>
      <JobStatus job={job.job} hideSuccess />
      <Alerts error={action.error} message={action.message} />
      <div className="row" style={{ alignItems: "flex-start", gap: 16, marginBottom: 10 }}>
        <div style={{ textAlign: "center" }}>
          {avatar ? <img src={assetUrl(project.id, "avatar", avatar.version)} alt="" style={{ width: 120, height: 120, borderRadius: "50%", objectFit: "cover", border: "1px solid var(--border)" }} />
            : <div className="img-placeholder" style={{ width: 120, height: 120, borderRadius: "50%", aspectRatio: "1" }}>аватар</div>}
          <div className="small muted">Аватар</div>
        </div>
        <div style={{ flex: 1, minWidth: 260 }}>
          {cover ? <img src={assetUrl(project.id, "cover", cover.version)} alt="" style={{ width: "100%", aspectRatio: "3/1", objectFit: "cover", borderRadius: 10, border: "1px solid var(--border)" }} />
            : <div className="img-placeholder" style={{ aspectRatio: "3/1", borderRadius: 10 }}>обложка (шапка группы)</div>}
          <div className="small muted">Обложка</div>
        </div>
      </div>
      <div className="row">
        <button className="primary" disabled={action.busy || job.running} onClick={() => generate(["avatar", "cover"])}>{avatar || cover ? "🔄 Перерисовать оба" : "✨ Сгенерировать аватар и обложку"}</button>
        {(avatar || cover) && <>
          <button className="small" disabled={job.running} onClick={() => generate(["avatar"])}>Только аватар</button>
          <button className="small" disabled={job.running} onClick={() => generate(["cover"])}>Только обложку</button>
        </>}
        {notUploaded && <button className="small" disabled={action.busy} onClick={async () => {
          const r = await action.run(() => api<Record<string, string>>(`/projects/${project.id}/design/upload`, { method: "POST" }));
          if (r) { const bad = Object.entries(r).filter(([, v]) => v !== "ok"); if (bad.length) action.setError(bad.map(([, v]) => v).join("\n")); else action.setMessage("Загружено в VK"); reload(); }
        }}>⬆️ Загрузить в VK</button>}
      </div>
      {!project.setup_proposal?.design && !project.brand?.style && <Hint>Сначала запустите AI-анализ или импортируйте стиль с сайта — из них берётся описание для картинок.</Hint>}
    </div>
  );
}
