"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Community } from "@/lib/types";
import { Alerts, Empty, Field, Hint, Modal, useAction, useLoad } from "@/components/ui";

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
      <div className="page-sub">Группы VK, где ваши аккаунты — администраторы. Здесь же включается приём комментариев и сообщений.</div>
      <Alerts error={error || action.error} message={action.message} />
      <Hint>
        <b>Как включить приём сообщений:</b> 1) в VK откройте сообщество → Управление → Работа с API → Ключи доступа → «Создать ключ» (права: сообщения, управление, фото, стена);
        2) здесь нажмите «🔑 Ключ сообщества» и вставьте его; 3) в поле «Приём сообщений» выберите <b>Long Poll</b>.
      </Hint>
      {data && data.length === 0 && <div className="card"><Empty icon="👥" title="Сообществ пока нет">Они появятся после нажатия «Проверить» на странице <Link href="/accounts">Аккаунты VK</Link> или после подключения в проекте.</Empty></div>}
      <div className="grid-3">
        {(data || []).map((c) => (
          <div key={c.id} className="card" style={{ marginBottom: 0 }}>
            <div className="row between">
              <div><a href={`https://vk.com/${c.screen_name || "club" + c.vk_group_id}`} target="_blank" rel="noreferrer"><b>{c.name}</b></a><div className="small muted">ID {c.vk_group_id} · {c.members_count ?? "—"} участн.</div></div>
              {c.project_id ? <span className="badge ok">в проекте</span> : <span className="badge">свободно</span>}
            </div>
            <div className="meta-line" style={{ margin: "10px 0" }}>
              <span>🚀 {c.project_id ? <Link href={`/projects/${c.project_id}`}>{names[c.project_id] || `Проект #${c.project_id}`}</Link> : "не подключено к проекту"}</span>
              <span>🔑 ключ {c.has_community_token ? "добавлен" : "не добавлен"}</span>
            </div>
            {c.last_error && <div className="alert err small">⚠️ <div>{c.last_error}</div></div>}
            <Field label="Приём сообщений и комментариев">
              <select value={c.event_mode} onChange={(e) => act(() => api(`/communities/${c.id}/events`, { method: "POST", json: { mode: e.target.value } }), e.target.value === "none" ? "Приём выключен" : "Приём сообщений включён")}>
                <option value="none">Выключен</option>
                <option value="longpoll" disabled={!c.has_community_token}>Long Poll (рекомендуется){c.has_community_token ? "" : " — нужен ключ"}</option>
                <option value="callback">Callback API (нужен публичный адрес сервера)</option>
              </select>
            </Field>
            <div className="row">
              <button className={`small ${c.has_community_token ? "" : "primary"}`} onClick={() => { setEdit(c); setToken(""); }}>🔑 Ключ сообщества</button>
              <button className="small" onClick={() => act(() => api(`/communities/${c.id}/sync`, { method: "POST" }), "Данные обновлены")}>🔄 Обновить</button>
            </div>
            <div className="small muted" style={{ marginTop: 8 }}>Синхронизировано {fmtDate(c.last_synced_at)}</div>
          </div>
        ))}
      </div>
      {edit && (
        <Modal title={`Ключ сообщества «${edit.name}»`} onClose={() => setEdit(null)}>
          <p className="small muted">VK → сообщество → Управление → Работа с API → Ключи доступа → «Создать ключ». Отметьте все права (управление сообществом, сообщения, фотографии, стена, документы). Ключ хранится зашифрованным. С ним посты и ответы работают без токена аккаунта.</p>
          <Field label="Ключ доступа"><input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="vk1.a…" /></Field>
          <div className="row">
            <button className="primary" disabled={!token} onClick={async () => { await act(() => api(`/communities/${edit.id}`, { method: "PATCH", json: { community_token: token } }), "Ключ сохранён — теперь можно включить Long Poll"); setEdit(null); }}>Сохранить</button>
            {edit.has_community_token && <button className="danger" onClick={async () => { await act(() => api(`/communities/${edit.id}`, { method: "PATCH", json: { community_token: "" } }), "Ключ удалён"); setEdit(null); }}>Удалить ключ</button>}
          </div>
        </Modal>
      )}
    </>
  );
}
