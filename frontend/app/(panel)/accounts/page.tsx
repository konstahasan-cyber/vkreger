"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Account, Proxy } from "@/lib/types";
import { Alerts, Badge, Field, Modal, useAction, useLoad } from "@/components/ui";

export default function AccountsPage() {
  const { data: accounts, reload, error } = useLoad<Account[]>("/accounts");
  const { data: proxies, reload: reloadProxies } = useLoad<Proxy[]>("/proxies");
  const action = useAction();
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", access_token: "", proxy_id: "", auto_replace_proxy: true });
  const [groupsOf, setGroupsOf] = useState<Account | null>(null);

  const freeProxies = (proxies || []).filter((p) => !p.account_id && p.status !== "dead");

  async function add() {
    const created = await action.run(() => api<Account>("/accounts", {
      method: "POST",
      json: { ...form, proxy_id: form.proxy_id ? Number(form.proxy_id) : null },
    }), "Аккаунт добавлен");
    if (created) {
      setShowAdd(false);
      setForm({ name: "", access_token: "", proxy_id: "", auto_replace_proxy: true });
      reload();
      reloadProxies();
    }
  }

  const act = async (fn: () => Promise<unknown>, ok: string) => { await action.run(fn, ok); reload(); reloadProxies(); };

  return (
    <>
      <div className="topbar"><h1>VK-аккаунты</h1><button className="primary" onClick={() => setShowAdd(true)}>+ Добавить аккаунт</button></div>
      <Alerts error={error || action.error} message={action.message} />
      <div className="card small muted">
        Импортируйте токены своих аккаунтов: user access token приложения VK (VK ID / OAuth) с правами wall, groups, photos, stats, offline.
        Токены хранятся в БД в зашифрованном виде и больше не показываются.
      </div>
      <div className="card table-wrap">
        <table>
          <thead><tr><th>#</th><th>Название</th><th>VK user</th><th>Статус</th><th>Proxy</th><th>Сообщества</th><th>Проверен</th><th>Ошибка</th><th /></tr></thead>
          <tbody>
            {(accounts || []).map((a) => (
              <tr key={a.id}>
                <td>{a.id}</td>
                <td><b>{a.name}</b><div className="small muted">{[a.info.first_name, a.info.last_name].filter(Boolean).join(" ")}</div></td>
                <td>{a.vk_user_id ? <a href={`https://vk.com/id${a.vk_user_id}`} target="_blank" rel="noreferrer">id{a.vk_user_id}</a> : "—"}</td>
                <td><Badge value={a.status} /></td>
                <td>
                  <select value={a.proxy_id ?? ""} onChange={(e) => act(() => api(`/accounts/${a.id}/proxy`, { method: "PUT", json: { proxy_id: e.target.value ? Number(e.target.value) : null } }), "Proxy обновлён")}>
                    <option value="">Без proxy</option>
                    {a.proxy_id && <option value={a.proxy_id}>{a.proxy_display} ({a.proxy_status})</option>}
                    {freeProxies.map((p) => <option key={p.id} value={p.id}>{p.scheme}://{p.host}:{p.port} {p.country_code || ""}</option>)}
                  </select>
                  <label className="small row" style={{ marginTop: 4 }}>
                    <input type="checkbox" style={{ width: "auto" }} checked={a.auto_replace_proxy}
                      onChange={(e) => act(() => api(`/accounts/${a.id}`, { method: "PATCH", json: { auto_replace_proxy: e.target.checked } }), "Сохранено")} />
                    автозамена умершего proxy
                  </label>
                </td>
                <td><button className="small" onClick={() => setGroupsOf(a)}>{a.groups_cache.length} шт.</button></td>
                <td className="small">{fmtDate(a.last_checked_at)}</td>
                <td className="small" style={{ maxWidth: 220 }}>{a.last_error || ""}</td>
                <td>
                  <div className="row">
                    <button className="small" disabled={action.busy} onClick={() => act(() => api(`/accounts/${a.id}/check`, { method: "POST" }), "Проверено")}>Проверить</button>
                    <button className="small" disabled={action.busy} onClick={() => act(() => api(`/accounts/${a.id}/refresh`, { method: "POST" }), "Данные и сообщества обновлены")}>Обновить</button>
                    <button className="small danger" onClick={() => confirm(`Удалить аккаунт ${a.name}?`) && act(() => api(`/accounts/${a.id}`, { method: "DELETE" }), "Удалён")}>Удалить</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {accounts && accounts.length === 0 && <p className="muted">Аккаунтов пока нет.</p>}
      </div>

      {showAdd && (
        <Modal title="Новый VK-аккаунт" onClose={() => setShowAdd(false)}>
          <Alerts error={action.error} />
          <Field label="Название"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Access token"><textarea value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} placeholder="vk1.a...." /></Field>
          <Field label="Proxy (необязательно)">
            <select value={form.proxy_id} onChange={(e) => setForm({ ...form, proxy_id: e.target.value })}>
              <option value="">Без proxy</option>
              {freeProxies.map((p) => <option key={p.id} value={p.id}>{p.scheme}://{p.host}:{p.port} — {p.status} {p.country || ""}</option>)}
            </select>
          </Field>
          <label className="row"><input type="checkbox" style={{ width: "auto" }} checked={form.auto_replace_proxy} onChange={(e) => setForm({ ...form, auto_replace_proxy: e.target.checked })} /> Автоматически заменять умерший proxy</label>
          <div className="row" style={{ marginTop: 12 }}><button className="primary" disabled={action.busy || !form.name || !form.access_token} onClick={add}>{action.busy ? "Проверка…" : "Добавить и проверить"}</button></div>
        </Modal>
      )}
      {groupsOf && (
        <Modal title={`Сообщества аккаунта ${groupsOf.name}`} onClose={() => setGroupsOf(null)}>
          <table><thead><tr><th>ID</th><th>Название</th><th>Участники</th></tr></thead>
            <tbody>{groupsOf.groups_cache.map((g) => <tr key={g.id}><td>{g.id}</td><td><a href={`https://vk.com/${g.screen_name || "club" + g.id}`} target="_blank" rel="noreferrer">{g.name}</a></td><td>{g.members_count ?? "—"}</td></tr>)}</tbody>
          </table>
        </Modal>
      )}
    </>
  );
}
