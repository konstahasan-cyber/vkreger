"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, qs } from "@/lib/api";
import type { Job } from "@/lib/types";
import { Alerts, Empty, Field, Hint, JobStatus, Modal, useAction, useJob, useLoad } from "@/components/ui";

interface NetworkSummary { name: string; projects: number }
interface NetworkProject {
  project_id: number; name: string; status: string; community_id: number | null; vk_group_id: number | null;
  persona: string | null; posts: Record<string, number>; total_posts: number;
}
interface ParsedItem { line: number; group: string | null; token: string | null; label: string | null; error: string | null }
interface BulkResult { line: number; group: string | null; label: string | null; ok: boolean; error?: string; project_id?: number; name?: string; created?: boolean; persona?: string }
interface PostBrief { id: number; project_id: number; project: string; title: string; status: string; start: string }
interface Pair { rewrite: PostBrief; keep: PostBrief; reasons: string[]; can_rewrite: boolean }

const TONES: [string, string][] = [["friendly", "Дружелюбный"], ["expert", "Экспертный"], ["simple", "Простой"], ["selling", "Продающий"]];
const GOALS: [string, string][] = [["leads", "Заявки"], ["sales", "Продажи"], ["reach", "Охваты"], ["expertise", "Экспертность"], ["traffic", "Трафик на сайт"]];
const FREQ: [string, string, number, number][] = [
  // value, label, every N days, posts per day
  ["1x1", "Каждый день", 1, 1], ["2x1", "Через день", 2, 1], ["1x2", "2 раза в день", 1, 2], ["3x1", "Раз в 3 дня", 3, 1],
];

const tomorrow = () => new Date(Date.now() + 86400000).toISOString().slice(0, 10);

function Schedule({ value, onChange }: { value: ScheduleState; onChange: (v: ScheduleState) => void }) {
  const freq = FREQ.find((f) => f[0] === value.freq) || FREQ[0];
  return (
    <>
      <div className="form-grid">
        <Field label="На сколько дней писать посты"><input type="number" min={1} max={60} value={value.days} onChange={(e) => onChange({ ...value, days: Number(e.target.value) })} /></Field>
        <Field label="Как часто выкладывать">
          <select value={value.freq} onChange={(e) => onChange({ ...value, freq: e.target.value })}>{FREQ.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </Field>
        <Field label={freq[3] > 1 ? "Время 1-го поста" : "Во сколько"}><input type="time" value={value.time1} onChange={(e) => onChange({ ...value, time1: e.target.value })} /></Field>
        {freq[3] > 1 && <Field label="Время 2-го поста"><input type="time" value={value.time2} onChange={(e) => onChange({ ...value, time2: e.target.value })} /></Field>}
        <Field label="Начиная с"><input type="date" value={value.start} onChange={(e) => onChange({ ...value, start: e.target.value })} /></Field>
      </div>
      <label className="check"><input type="checkbox" checked={value.withImage} onChange={(e) => onChange({ ...value, withImage: e.target.checked })} /> 🖼 Рисовать картинки к постам (дольше и дороже; с одним ключом сообщества VK картинки не принимает)</label>
      <label className="check" style={{ marginTop: 6 }}><input type="checkbox" checked={value.autoSchedule} onChange={(e) => onChange({ ...value, autoSchedule: e.target.checked })} /> ⏰ Сразу ставить в очередь публикации (без ручной проверки)</label>
      <p className="small muted" style={{ marginTop: 8 }}>Время у групп немного сдвигается (+4 минуты на каждую группу), чтобы все не публиковали в одну минуту.</p>
    </>
  );
}

interface ScheduleState { days: number; freq: string; time1: string; time2: string; start: string; withImage: boolean; autoSchedule: boolean }
const defaultSchedule = (): ScheduleState => ({ days: 14, freq: "1x1", time1: "10:00", time2: "18:00", start: tomorrow(), withImage: false, autoSchedule: false });

function scheduleParams(s: ScheduleState) {
  const freq = FREQ.find((f) => f[0] === s.freq) || FREQ[0];
  const times = freq[3] > 1 ? [s.time1, s.time2] : [s.time1];
  return { days: s.days, cadence_days: freq[2], post_times: times, start_date: s.start || null, with_image: s.withImage, auto_schedule: s.autoSchedule };
}

function postsPerGroup(s: ScheduleState) {
  const freq = FREQ.find((f) => f[0] === s.freq) || FREQ[0];
  return Math.min(60, Math.ceil(s.days / freq[2]) * freq[3]);
}

export default function NetworksPage() {
  const { data: networks, reload: reloadNetworks } = useLoad<NetworkSummary[]>("/networks");
  const [current, setCurrent] = useState<string>("");
  const [mode, setMode] = useState<"view" | "new">("view");
  useEffect(() => {
    if (!networks) return;
    if (networks.length === 0) setMode("new");
    else if (!current) setCurrent(networks[0].name);
  }, [networks, current]);

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Сеть групп</h1>
          <div className="page-sub">Много групп на одну тему: подключение пачкой по ключам, свой «голос» у каждой группы и проверка, чтобы посты разных групп не повторяли друг друга.</div>
        </div>
        <div className="row">
          {(networks || []).length > 0 && (
            <select value={mode === "new" ? "" : current} onChange={(e) => { setCurrent(e.target.value); setMode("view"); }} style={{ width: 240 }}>
              {mode === "new" && <option value="">— новая сеть —</option>}
              {(networks || []).map((n) => <option key={n.name} value={n.name}>{n.name} ({n.projects})</option>)}
            </select>
          )}
          <button className="primary" onClick={() => setMode("new")}>＋ Быстрый ввод групп</button>
        </div>
      </div>
      {mode === "new"
        ? <BulkForm networks={networks || []} onDone={(name) => { reloadNetworks(); setCurrent(name); setMode("view"); }} />
        : current ? <NetworkView key={current} name={current} onChanged={reloadNetworks} /> : null}
    </>
  );
}

function BulkForm({ networks, onDone }: { networks: NetworkSummary[]; onDone: (name: string) => void }) {
  const [network, setNetwork] = useState(networks[0]?.name || "Кадровое агентство");
  const [brief, setBrief] = useState({ business_name: "", niche: "", city: "", target_audience: "", product_description: "", advantages: "", website: "", contacts: "", tone: "friendly", goal: "leads" });
  const [lines, setLines] = useState("");
  const [parsed, setParsed] = useState<{ items: ParsedItem[]; valid: number } | null>(null);
  const [schedule, setSchedule] = useState<ScheduleState>(defaultSchedule());
  const [generate, setGenerate] = useState(true);
  const [results, setResults] = useState<BulkResult[] | null>(null);
  const action = useAction();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const existing = networks.some((n) => n.name === network.trim());

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!lines.trim()) { setParsed(null); return; }
    timer.current = setTimeout(() => {
      api<{ items: ParsedItem[]; valid: number }>("/networks/parse", { method: "POST", json: { lines } }).then(setParsed).catch((e) => action.setError((e as Error).message));
    }, 400);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines]);

  const set = (k: keyof typeof brief) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setBrief({ ...brief, [k]: e.target.value });
  const valid = parsed?.valid || 0;
  const perGroup = postsPerGroup(schedule);
  const canSubmit = valid > 0 && network.trim() && (existing || brief.business_name.trim());

  const submit = async () => {
    const body = {
      network: network.trim(), lines, generate, ...scheduleParams(schedule),
      brief: { ...brief, business_name: brief.business_name.trim() || network.trim() },
    };
    const r = await action.run(() => api<{ results: BulkResult[]; connected: number; job: Job | null }>("/networks/bulk", { method: "POST", json: body }));
    if (!r) return;
    setResults(r.results);
    if (r.connected === 0) { action.setError("Ни одна группа не подключилась — причины в таблице ниже."); return; }
    action.setMessage(`Подключено групп: ${r.connected}.${r.job ? " AI пишет посты — прогресс виден на странице сети." : ""}`);
    if (r.connected > 0) setLines("");
  };

  return (
    <>
      <Alerts error={action.error} message={action.message} />
      {results && (
        <div className="card">
          <div className="card-head"><h2>Результат подключения</h2>{results.some((r) => r.ok) && <button className="primary" onClick={() => onDone(network.trim())}>Перейти к сети →</button>}</div>
          <table>
            <thead><tr><th>Строка</th><th>Группа</th><th>Результат</th><th>Голос</th></tr></thead>
            <tbody>{results.map((r) => (
              <tr key={r.line}>
                <td>{r.line}</td>
                <td>{r.name || r.group || r.label || "—"}</td>
                <td>{r.ok ? <span className="badge ok">{r.created ? "подключена" : "уже была — добавлена в сеть"}</span> : <span style={{ color: "var(--danger)" }}>⚠️ {r.error}</span>}</td>
                <td className="small">{r.persona || ""}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <div className="card">
        <h2>1. Название сети</h2>
        <Field label="Как назвать эту пачку групп" hint={existing ? "Такая сеть уже есть — новые группы добавятся в неё и получат её стратегию." : "Например: «Кадровое агентство». Группы одной сети пишут на одну тему, но разными голосами."}>
          <input value={network} onChange={(e) => setNetwork(e.target.value)} list="networks-list" />
          <datalist id="networks-list">{networks.map((n) => <option key={n.name} value={n.name} />)}</datalist>
        </Field>
      </div>

      {!existing && (
        <div className="card">
          <h2>2. О чём пишут группы</h2>
          <p className="small muted">Это общее для всех групп сети. AI один раз составит стратегию и рубрики, а потом раздаст группам разные голоса и темы.</p>
          <div className="form-grid">
            <Field label="Название бизнеса *"><input value={brief.business_name} onChange={set("business_name")} placeholder="Кадровое агентство «Старт»" /></Field>
            <Field label="Ниша"><input value={brief.niche} onChange={set("niche")} placeholder="подбор персонала, вакансии" /></Field>
            <Field label="Город / регион"><input value={brief.city} onChange={set("city")} placeholder="Москва и МО" /></Field>
            <Field label="Сайт"><input value={brief.website} onChange={set("website")} placeholder="https://…" /></Field>
          </div>
          <Field label="Для кого (аудитория)"><input value={brief.target_audience} onChange={set("target_audience")} placeholder="соискатели без опыта, вахтовики, работодатели малого бизнеса" /></Field>
          <Field label="Что предлагаете"><textarea rows={3} value={brief.product_description} onChange={set("product_description")} placeholder="Подбираем работу бесплатно для соискателя, вакансии на складах, в магазинах, вахта с проживанием…" /></Field>
          <div className="form-grid">
            <Field label="Преимущества"><input value={brief.advantages} onChange={set("advantages")} placeholder="официальное оформление, выплаты без задержек" /></Field>
            <Field label="Контакты для CTA"><input value={brief.contacts} onChange={set("contacts")} placeholder="пишите в сообщения группы" /></Field>
            <Field label="Тон"><select value={brief.tone} onChange={set("tone")}>{TONES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
            <Field label="Цель"><select value={brief.goal} onChange={set("goal")}>{GOALS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          </div>
        </div>
      )}

      <div className="card">
        <h2>{existing ? "2" : "3"}. Группы и ключи</h2>
        <p className="small muted">Вставьте по одной группе на строку: <b>ID и ключ доступа</b>. Подойдёт копия из таблицы или чата. Разделитель любой: пробел, табуляция, «;», «,» или «|». ID можно не писать, тогда группа определится по ключу.</p>
        <textarea rows={8} value={lines} onChange={(e) => setLines(e.target.value)} spellCheck={false} style={{ fontFamily: "ui-monospace, monospace", fontSize: 13 }}
          placeholder={"123456789 vk1.a.AbCdEf…\nhttps://vk.com/club987654321; vk1.a.XyZ…\nvk1.a.ТолькоКлюч…"} />
        {parsed && (
          <div style={{ marginTop: 10 }}>
            <div className="row small" style={{ marginBottom: 6 }}>
              <span className="badge ok">распознано групп: {valid}</span>
              {parsed.items.length - valid > 0 && <span className="badge err">с ошибкой: {parsed.items.length - valid}</span>}
            </div>
            {parsed.items.some((i) => i.error) && (
              <ul className="small" style={{ margin: 0, paddingLeft: 18, color: "var(--danger)" }}>
                {parsed.items.filter((i) => i.error).map((i) => <li key={i.line}>строка {i.line}: {i.error}</li>)}
              </ul>
            )}
          </div>
        )}
        <Hint>Ключи хранятся в базе в зашифрованном виде, а в панели показываются только первые и последние символы. Где взять ключ: группа → Управление → Работа с API → Ключи доступа → «Создать ключ», отметьте все права.</Hint>
      </div>

      <div className="card">
        <h2>{existing ? "3" : "4"}. Посты</h2>
        <label className="check" style={{ marginBottom: 10 }}><input type="checkbox" checked={generate} onChange={(e) => setGenerate(e.target.checked)} /> ✨ Сразу написать посты для каждой группы</label>
        {generate && <Schedule value={schedule} onChange={setSchedule} />}
        {generate && valid > 0 && (
          <div className="alert info">📋 <div>Будет написано <b>{perGroup}</b> постов на группу × <b>{valid}</b> групп = <b>{perGroup * valid}</b> постов. У каждой группы свой голос и свои темы. Похожие на посты других групп AI автоматически переписывает.</div></div>
        )}
        <button className="primary big" disabled={!canSubmit || action.busy} onClick={submit}>
          {action.busy ? "Подключаем группы…" : generate ? `🚀 Подключить ${valid || ""} и написать посты` : `🔗 Подключить ${valid || ""}`}
        </button>
        {!canSubmit && valid > 0 && !existing && !brief.business_name.trim() && <div className="small muted" style={{ marginTop: 6 }}>Заполните «Название бизнеса».</div>}
      </div>
    </>
  );
}

function NetworkView({ name, onChanged }: { name: string; onChanged: () => void }) {
  const { data, reload, error } = useLoad<{ name: string; projects: NetworkProject[] }>(`/networks/detail${qs({ name })}`, [name]);
  const action = useAction();
  const [expected, setExpected] = useState<number | null>(null);
  const launch = useJob((j) => {
    reload();
    if (j.status === "success") setExpected(Number(j.result.posts_per_group) || null);
  });
  const dedupe = useJob((j) => {
    reload();
    if (j.status === "success") {
      const r = j.result as { similar_pairs: number; rewritten: number[]; failed: unknown[] };
      action.setMessage(r.rewritten.length ? `Переписано постов: ${r.rewritten.length}. Нажмите «Проверить похожесть» ещё раз, чтобы убедиться.` : "Похожих постов не найдено 👍");
      setPairs(null);
    }
  });
  const [showGen, setShowGen] = useState(false);
  const [schedule, setSchedule] = useState<ScheduleState>(defaultSchedule());
  const [pairs, setPairs] = useState<{ pairs: Pair[]; to_rewrite: number } | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  // resume progress after a reload of the page
  useEffect(() => {
    api<Job[]>("/jobs?limit=30").then((jobs) => {
      const active = jobs.find((j) => j.type === "network_launch" && j.params.network === name && (j.status === "pending" || j.status === "running"));
      if (active) launch.start(active);
      const recent = jobs.find((j) => j.type === "network_launch" && j.params.network === name && j.status === "success");
      if (recent) setExpected(Number(recent.result.posts_per_group) || null);
    }).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  const projects = data?.projects || [];
  const writing = expected != null && projects.some((p) => p.community_id && p.total_posts < expected);
  useEffect(() => {
    if (!launch.running && !writing) return;
    const t = setInterval(reload, 5000);
    return () => clearInterval(t);
  }, [launch.running, writing, reload]);

  const sum = (key: string) => projects.reduce((acc, p) => acc + (p.posts[key] || 0), 0);

  return (
    <>
      <Alerts error={error || action.error} message={action.message} />
      <JobStatus job={launch.job} hideSuccess />
      <JobStatus job={dedupe.job} hideSuccess />
      {writing && <div className="alert info"><span className="spinner" /><div>AI пишет посты для групп: <b>{projects.filter((p) => expected && p.total_posts >= expected).length}</b> из {projects.length} готовы. Страница обновляется сама, можно уйти и вернуться.</div></div>}

      <div className="grid" style={{ marginBottom: 16 }}>
        <div className="stat"><div className="label">Групп</div><div className="value">{projects.length}</div></div>
        <div className="stat"><div className="label">На проверке</div><div className="value">{sum("draft")}</div></div>
        <div className="stat"><div className="label">В очереди</div><div className="value">{sum("scheduled")}</div></div>
        <div className="stat"><div className="label">Опубликовано</div><div className="value">{sum("published")}</div></div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Группы сети «{name}»</h2>
          <div className="row">
            <button onClick={() => setShowAdd(true)}>＋ Добавить проекты</button>
            <button className="primary" disabled={launch.running} onClick={() => setShowGen(true)}>✨ Написать посты для всех</button>
          </div>
        </div>
        {projects.length === 0 ? <Empty icon="🔗" title="В сети пока нет групп" /> : (
          <table>
            <thead><tr><th>Группа</th><th>🎭 Голос</th><th>На проверке</th><th>В очереди</th><th>Опубликовано</th><th></th></tr></thead>
            <tbody>{projects.map((p) => (
              <tr key={p.project_id}>
                <td>
                  <Link href={`/projects/${p.project_id}`}><b>{p.name}</b></Link>
                  <div className="small muted">{p.vk_group_id ? <a href={`https://vk.com/club${p.vk_group_id}`} target="_blank" rel="noreferrer">club{p.vk_group_id}</a> : "сообщество не подключено"}</div>
                </td>
                <td className="small">{p.persona || "—"}</td>
                <td>{p.posts.draft || 0}{expected != null && p.total_posts < expected && <span className="small muted"> · пишется {p.total_posts}/{expected}</span>}</td>
                <td>{p.posts.scheduled || 0}</td>
                <td>{p.posts.published || 0}{p.posts.failed ? <span className="small" style={{ color: "var(--danger)" }}> · ошибок {p.posts.failed}</span> : null}</td>
                <td><Link className="small" href={`/content?project_id=${p.project_id}`}>Посты →</Link></td>
              </tr>
            ))}</tbody>
          </table>
        )}
        {sum("draft") > 0 && (
          <div className="row" style={{ marginTop: 12 }}>
            <button className="primary" disabled={action.busy} onClick={async () => {
              if (!confirm(`Одобрить все посты на проверке во всех группах сети (${sum("draft")})? Каждый встанет в очередь на своё время.`)) return;
              let approved = 0;
              const errors: string[] = [];
              await action.run(async () => {
                for (const p of projects.filter((x) => x.posts.draft)) {
                  const r = await api<{ approved: number; errors: string[] }>("/posts/approve-all", { method: "POST", json: { project_id: p.project_id } });
                  approved += r.approved;
                  errors.push(...r.errors);
                }
              });
              if (errors.length) action.setError(`Не одобрены: ${errors.slice(0, 5).join("; ")}`);
              action.setMessage(`Одобрено постов: ${approved}`);
              reload();
            }}>✓ Одобрить все посты сети ({sum("draft")})</button>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>🔍 Похожие посты в разных группах</h2>
          <div className="row">
            <button disabled={action.busy} onClick={async () => { const r = await action.run(() => api<{ pairs: Pair[]; to_rewrite: number }>(`/networks/similar${qs({ name })}`)); if (r) setPairs(r); }}>Проверить похожесть</button>
            {pairs && pairs.to_rewrite > 0 && (
              <button className="primary" disabled={dedupe.running} onClick={async () => {
                const j = await action.run(() => api<Job>("/networks/dedupe", { method: "POST", json: { network: name } }));
                if (j) dedupe.start(j);
              }}>✍️ Переписать все похожие ({pairs.to_rewrite})</button>
            )}
          </div>
        </div>
        <p className="small muted">Сравниваются заголовки, первые строки и смысл постов разных групп. Переписывается более новый неопубликованный пост: картинка и время публикации остаются прежними.</p>
        {pairs && pairs.pairs.length === 0 && <div className="alert ok">✅ <div>Похожих постов не найдено.</div></div>}
        {pairs && pairs.pairs.length > 0 && (
          <table>
            <thead><tr><th>Пост</th><th>Похож на</th><th>Почему</th><th></th></tr></thead>
            <tbody>{pairs.pairs.slice(0, 100).map((pair, i) => (
              <tr key={i}>
                <td><div className="small muted">{pair.rewrite.project}</div><Link href={`/content?post=${pair.rewrite.id}`}>{pair.rewrite.title}</Link><div className="small muted">«{pair.rewrite.start}»</div></td>
                <td><div className="small muted">{pair.keep.project}</div>{pair.keep.title}<div className="small muted">«{pair.keep.start}»</div></td>
                <td className="small">{pair.reasons.join(", ")}</td>
                <td>{pair.can_rewrite ? <RewriteButton postId={pair.rewrite.id} onDone={() => setPairs((cur) => cur && { ...cur, pairs: cur.pairs.filter((x) => x.rewrite.id !== pair.rewrite.id) })} /> : <span className="small muted">оба опубликованы</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>

      {showGen && (
        <Modal title={`Посты для всех групп «${name}»`} onClose={() => setShowGen(false)}>
          <Schedule value={schedule} onChange={setSchedule} />
          <div className="alert info">📋 <div><b>{postsPerGroup(schedule)}</b> постов на группу × <b>{projects.filter((p) => p.community_id).length}</b> групп. Каждая группа пишет своим голосом, а темы не пересекаются с другими группами.</div></div>
          <button className="primary big" disabled={launch.running} onClick={async () => {
            const j = await action.run(() => api<Job>("/networks/generate", { method: "POST", json: { network: name, ...scheduleParams(schedule) } }));
            if (j) { launch.start(j); setShowGen(false); setExpected(null); }
          }}>✨ Написать</button>
        </Modal>
      )}
      {showAdd && <AddProjects name={name} inNetwork={projects.map((p) => p.project_id)} onClose={() => setShowAdd(false)} onDone={() => { setShowAdd(false); reload(); onChanged(); }} />}
    </>
  );
}

function RewriteButton({ postId, onDone }: { postId: number; onDone: () => void }) {
  const action = useAction();
  return (
    <>
      <button className="small" disabled={action.busy} onClick={async () => { const r = await action.run(() => api(`/networks/rewrite/${postId}`, { method: "POST" })); if (r) onDone(); }}>
        {action.busy ? "Пишем…" : "✍️ Переписать"}
      </button>
      {action.error && <div className="small" style={{ color: "var(--danger)" }}>{action.error}</div>}
    </>
  );
}

function AddProjects({ name, inNetwork, onClose, onDone }: { name: string; inNetwork: number[]; onClose: () => void; onDone: () => void }) {
  const { data } = useLoad<{ id: number; name: string; network: string | null; community_name: string | null }[]>("/projects");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const action = useAction();
  const candidates = (data || []).filter((p) => !inNetwork.includes(p.id));
  return (
    <Modal title={`Добавить проекты в «${name}»`} onClose={onClose}>
      <p className="small muted">Подходит для групп, которые уже ведутся в панели: им назначатся разные голоса, а новые посты будут сверяться с постами других групп сети.</p>
      <Alerts error={action.error} />
      {candidates.length === 0 ? <p className="muted">Все проекты уже в этой сети.</p> : (
        <div style={{ maxHeight: 360, overflow: "auto", marginBottom: 12 }}>
          <label className="check" style={{ marginBottom: 8 }}><input type="checkbox" checked={selected.size === candidates.length} onChange={(e) => setSelected(e.target.checked ? new Set(candidates.map((c) => c.id)) : new Set())} /> <b>Выбрать все</b></label>
          {candidates.map((p) => (
            <label key={p.id} className="check" style={{ marginBottom: 6 }}>
              <input type="checkbox" checked={selected.has(p.id)} onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(p.id); else n.delete(p.id); return n; })} />
              {p.name}{p.community_name ? <span className="small muted"> · {p.community_name}</span> : null}{p.network ? <span className="small muted"> · сейчас в «{p.network}»</span> : null}
            </label>
          ))}
        </div>
      )}
      <button className="primary" disabled={!selected.size || action.busy} onClick={async () => {
        const r = await action.run(() => api("/networks/projects", { method: "POST", json: { network: name, project_ids: [...selected] } }));
        if (r) onDone();
      }}>Добавить ({selected.size})</button>
    </Modal>
  );
}
