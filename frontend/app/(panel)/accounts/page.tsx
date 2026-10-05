"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Account, Proxy } from "@/lib/types";
import { Alerts, Badge, Empty, Field, Hint, Modal, useAction, useLoad } from "@/components/ui";

function oauthLink(appId: string, offline: boolean) {
  const scope = ["wall", "groups", "photos", "stats", ...(offline ? ["offline"] : [])].join(",");
  return `https://oauth.vk.com/authorize?client_id=${appId}&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=${scope}&response_type=token&v=5.199`;
}

function TokenGuide() {
  const [appId, setAppId] = useState("");
  return (
    <details className="card soft" style={{ marginBottom: 14 }}>
      <summary><b>❓ Где взять токен</b></summary>
      <ol style={{ paddingLeft: 18, marginBottom: 0 }}>
        <li>На <a href="https://dev.vk.com" target="_blank" rel="noreferrer">dev.vk.com</a> → «Приложения» создайте своё приложение (лучше тип <b>Standalone</b>, если VK его предлагает — тогда работает автосоздание сообществ и бессрочный токен).</li>
        <li>Скопируйте его <b>ID</b> (число) и вставьте сюда:
          <input value={appId} onChange={(e) => setAppId(e.target.value.replace(/\D/g, ""))} placeholder="ID приложения, например 54805043" style={{ margin: "6px 0", maxWidth: 320, display: "block" }} />
          {appId && <div className="row"><a href={oauthLink(appId, true)} target="_blank" rel="noreferrer"><button className="small primary">Получить бессрочный токен</button></a><a href={oauthLink(appId, false)} target="_blank" rel="noreferrer"><button className="small">Если ошибка «invalid scope» — этот вариант</button></a></div>}
        </li>
        <li>Нажмите «Разрешить». В адресной строке открывшейся страницы скопируйте всё между <code>access_token=</code> и <code>&amp;expires_in</code>.</li>
        <li>Вставьте токен в форму. <b>Не берите «Защищённый» или «Сервисный» ключ</b> со страницы приложения — они не подходят.</li>
      </ol>
      <p className="small muted" style={{ marginTop: 8 }}>Если в адресе <code>expires_in</code> не 0 — токен временный, и через это время его нужно будет заменить кнопкой «Заменить токен».</p>
    </details>
  );
}

interface OAuthConfig { configured: boolean; app_id: number | null; flow: string; has_secret: boolean; offline: boolean; redirect_uri: string; https: boolean }

function OAuthSetup({ config, onSaved }: { config: OAuthConfig; onSaved: () => void }) {
  const action = useAction();
  const [appId, setAppId] = useState(config.app_id ? String(config.app_id) : "");
  const [secret, setSecret] = useState("");
  const [flow, setFlow] = useState(config.flow || "vkid");
  const [open, setOpen] = useState(!config.configured);
  const host = config.redirect_uri.replace(/^https?:\/\//, "").split("/")[0].split(":")[0];
  if (!open) return <button className="small ghost" onClick={() => setOpen(true)}>⚙️ Настройки входа через VK</button>;
  const copy = (
    <div className="row" style={{ margin: "6px 0" }}><code style={{ background: "var(--panel-2)", padding: "6px 10px", borderRadius: 8 }}>{config.redirect_uri}</code>
      <button className="small" onClick={() => navigator.clipboard?.writeText(config.redirect_uri)}>📋 Скопировать</button></div>
  );
  return (
    <div className="card step-card">
      <h2>🔐 Настройка входа через VK (один раз)</h2>
      <p className="muted">Токен получает сам сервер — VK не блокирует его из-за другого IP, и ничего не нужно копировать из адресной строки.</p>
      <div className="choices">
        <button type="button" className={`choice ${flow === "vkid" ? "active" : ""}`} onClick={() => setFlow("vkid")}>
          <b>VK ID (рекомендуется)</b><span className="small muted">Токен продлевается автоматически. Нужен адрес панели с https://</span>
        </button>
        <button type="button" className={`choice ${flow === "classic" ? "active" : ""}`} onClick={() => setFlow("classic")}>
          <b>Классическое приложение VK</b><span className="small muted">Нужен «Защищённый ключ». Токен без автопродления.</span>
        </button>
      </div>
      {flow === "vkid" && !config.https && <Hint kind="warn">Сейчас панель открыта по http — VK ID требует https. Сначала подключите домен (команда на сервере <code>vk hostdomain …</code>), затем вернитесь сюда.</Hint>}
      {flow === "vkid" ? (
        <ol style={{ paddingLeft: 18 }}>
          <li>Откройте <a href="https://id.vk.com/about/business/go" target="_blank" rel="noreferrer">кабинет VK ID для бизнеса</a> и создайте приложение для <b>Web</b> (сайта).</li>
          <li>В настройках приложения укажите <b>базовый домен</b> <code>{host}</code> и <b>доверенный Redirect URL</b>:{copy}</li>
          <li>Включите доступы: стена, сообщества, фотографии, статистика (если кабинет их предлагает).</li>
          <li>Скопируйте <b>ID приложения</b> сюда.</li>
        </ol>
      ) : (
        <ol style={{ paddingLeft: 18 }}>
          <li>В настройках приложения на <a href="https://dev.vk.com/ru/admin/apps-list" target="_blank" rel="noreferrer">dev.vk.com</a> найдите <b>«Доверенный redirect URL»</b> и вставьте:{copy}</li>
          <li>Там же: «Ключи доступа» → <b>«Защищённый ключ»</b> → «Показать» и скопируйте сюда.</li>
        </ol>
      )}
      <Alerts error={action.error} />
      <div className="form-grid">
        <Field label="ID приложения"><input value={appId} onChange={(e) => setAppId(e.target.value.replace(/\D/g, ""))} placeholder="54805330" /></Field>
        {flow === "classic" && <Field label="Защищённый ключ" hint={config.has_secret ? "Уже сохранён. Заполните, только если хотите заменить." : undefined}><input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} /></Field>}
      </div>
      <div className="row">
        <button className="primary" disabled={action.busy || !appId || (flow === "classic" && !config.has_secret && !secret)} onClick={async () => {
          const r = await action.run(() => api("/vk/oauth/config", { method: "PUT", json: { app_id: Number(appId), secret: secret || null, offline: false, flow } }));
          if (r) { setSecret(""); setOpen(false); onSaved(); }
        }}>Сохранить</button>
        {config.configured && <button className="ghost" onClick={() => setOpen(false)}>Свернуть</button>}
      </div>
    </div>
  );
}

function tokenExpiry(a: Account): { text: string; expired: boolean } | null {
  const raw = (a.info as { token_expires_at?: string | null }).token_expires_at;
  if (!raw) return null;
  const d = new Date(raw);
  return { text: d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }), expired: d.getTime() < Date.now() };
}

export default function AccountsPage() {
  const { data: accounts, reload, error } = useLoad<Account[]>("/accounts");
  const { data: proxies, reload: reloadProxies } = useLoad<Proxy[]>("/proxies");
  const action = useAction();
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", access_token: "", proxy_id: "", auto_replace_proxy: true });
  const [replaceFor, setReplaceFor] = useState<Account | null>(null);
  const [newToken, setNewToken] = useState("");
  const [groupsOf, setGroupsOf] = useState<Account | null>(null);
  const { data: oauthConfig, reload: reloadOAuth } = useLoad<OAuthConfig>("/vk/oauth/config");
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (q.get("vk_ok")) action.setMessage(q.get("vk_ok"));
    if (q.get("vk_error")) action.setError(q.get("vk_error"));
    if (q.get("vk_ok") || q.get("vk_error")) window.history.replaceState(null, "", "/accounts");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const vkLogin = async (body: { account_id?: number; name?: string }) => {
    const r = await action.run(() => api<{ url: string }>("/vk/oauth/start", { method: "POST", json: body }));
    if (r) window.location.href = r.url;
  };

  const freeProxies = (proxies || []).filter((p) => !p.account_id && p.status !== "dead");
  const act = async (fn: () => Promise<unknown>, ok: string) => { await action.run(fn, ok); reload(); reloadProxies(); };

  async function add() {
    const created = await action.run(() => api<Account>("/accounts", { method: "POST", json: { ...form, proxy_id: form.proxy_id ? Number(form.proxy_id) : null } }));
    if (created) {
      setShowAdd(false);
      setForm({ name: "", access_token: "", proxy_id: "", auto_replace_proxy: true });
      action.setMessage(created.status === "active" ? `Аккаунт «${created.name}» подключён` : `Аккаунт добавлен, но токен не работает: ${created.last_error}`);
      reload(); reloadProxies();
    }
  }

  return (
    <>
      <div className="topbar">
        <div><h1>Аккаунты VK</h1><div className="page-sub">От имени этих аккаунтов публикуются посты. Токены хранятся зашифрованными.</div></div>
        <div className="row">
          {oauthConfig?.configured && <button className="primary big" onClick={() => vkLogin({ name: `Аккаунт ${(accounts?.length || 0) + 1}` })}>🔐 Войти через VK</button>}
          <button className={oauthConfig?.configured ? "" : "primary big"} onClick={() => setShowAdd(true)}>+ Добавить по токену</button>
        </div>
      </div>
      <Alerts error={error || action.error} message={action.message} />
      {oauthConfig && <div style={{ marginBottom: 16 }}><OAuthSetup config={oauthConfig} onSaved={reloadOAuth} /></div>}
      {accounts && accounts.length === 0 && (
        <div className="card"><Empty icon="👤" title="Аккаунтов пока нет"><button className="primary" onClick={() => setShowAdd(true)}>+ Добавить аккаунт</button></Empty></div>
      )}
      <div className="grid-3">
        {(accounts || []).map((a) => (
          <div key={a.id} className="card" style={{ marginBottom: 0 }}>
            <div className="row between">
              <div className="row">
                {a.info.photo ? <img src={a.info.photo} alt="" style={{ width: 40, height: 40, borderRadius: "50%" }} /> : <span style={{ fontSize: 28 }}>👤</span>}
                <div><b>{a.name}</b><div className="small muted">{[a.info.first_name, a.info.last_name].filter(Boolean).join(" ") || "—"}{a.vk_user_id && <> · <a href={`https://vk.com/id${a.vk_user_id}`} target="_blank" rel="noreferrer">id{a.vk_user_id}</a></>}</div></div>
              </div>
              <Badge value={a.status} />
            </div>
            {a.status !== "active" && a.last_error && <div className="alert err small" style={{ marginTop: 10 }}>⚠️ <div>{a.last_error}<br /><b>Решение:</b> {oauthConfig?.configured ? "нажмите «Войти заново»." : "настройте «Вход через VK» выше и нажмите «Войти заново»."}</div></div>}
            <div className="meta-line" style={{ margin: "10px 0" }}>
              <span>👥 <a style={{ cursor: "pointer" }} onClick={() => setGroupsOf(a)}>сообществ: {a.groups_cache.length}</a></span>
              <span>🕐 проверен {fmtDate(a.last_checked_at)}</span>
              {tokenExpiry(a) && <span style={{ color: tokenExpiry(a)!.expired ? "var(--danger)" : undefined }}>🔑 токен {tokenExpiry(a)!.expired ? "истёк" : "до"} {tokenExpiry(a)!.text}</span>}
            </div>
            <Field label="Прокси">
              <select value={a.proxy_id ?? ""} onChange={(e) => act(() => api(`/accounts/${a.id}/proxy`, { method: "PUT", json: { proxy_id: e.target.value ? Number(e.target.value) : null } }), "Прокси обновлён")}>
                <option value="">Без прокси (напрямую)</option>
                {a.proxy_id && <option value={a.proxy_id}>{a.proxy_display} — {a.proxy_status}</option>}
                {freeProxies.map((p) => <option key={p.id} value={p.id}>{p.host}:{p.port} {p.country_code || ""}</option>)}
              </select>
            </Field>
            <label className="check small" style={{ marginBottom: 12 }}><input type="checkbox" checked={a.auto_replace_proxy} onChange={(e) => act(() => api(`/accounts/${a.id}`, { method: "PATCH", json: { auto_replace_proxy: e.target.checked } }), "Сохранено")} /> менять прокси, если он перестал работать</label>
            <div className="row">
              <button className="small" disabled={action.busy} onClick={() => act(() => api(`/accounts/${a.id}/refresh`, { method: "POST" }), "Проверено, список сообществ обновлён")}>🔄 Проверить</button>
              {oauthConfig?.configured && <button className={`small ${a.status !== "active" ? "primary" : ""}`} onClick={() => vkLogin({ account_id: a.id })}>🔐 Войти заново</button>}
              <button className={`small ${a.status !== "active" && !oauthConfig?.configured ? "primary" : ""}`} onClick={() => { setReplaceFor(a); setNewToken(""); }}>🔑 Заменить токен</button>
              <button className="small ghost" onClick={() => confirm(`Удалить аккаунт «${a.name}»? Проекты, привязанные к нему, останутся без аккаунта.`) && act(() => api(`/accounts/${a.id}`, { method: "DELETE" }), "Удалён")}>🗑</button>
            </div>
          </div>
        ))}
      </div>

      {showAdd && (
        <Modal title="Новый аккаунт VK" onClose={() => setShowAdd(false)}>
          <TokenGuide />
          <Alerts error={action.error} />
          <Field label="Название (для вас)"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Например: Основной" /></Field>
          <Field label="Токен"><textarea value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} placeholder="vk1.a.…" /></Field>
          <Field label="Прокси (необязательно)">
            <select value={form.proxy_id} onChange={(e) => setForm({ ...form, proxy_id: e.target.value })}>
              <option value="">Без прокси</option>
              {freeProxies.map((p) => <option key={p.id} value={p.id}>{p.host}:{p.port} — {p.status} {p.country || ""}</option>)}
            </select>
          </Field>
          <button className="primary big" disabled={action.busy || !form.name || !form.access_token} onClick={add}>{action.busy ? "Проверяем…" : "Добавить и проверить"}</button>
        </Modal>
      )}
      {replaceFor && (
        <Modal title={`Новый токен для «${replaceFor.name}»`} onClose={() => setReplaceFor(null)}>
          <TokenGuide />
          <Alerts error={action.error} />
          <Field label="Новый токен" hint="Проекты и сообщества останутся привязаны к этому аккаунту."><textarea value={newToken} onChange={(e) => setNewToken(e.target.value)} placeholder="vk1.a.…" /></Field>
          <button className="primary big" disabled={action.busy || newToken.trim().length < 10} onClick={async () => {
            const u = await action.run(() => api<Account>(`/accounts/${replaceFor.id}`, { method: "PATCH", json: { access_token: newToken.trim() } }));
            if (u) { setReplaceFor(null); action.setMessage(u.status === "active" ? "Токен обновлён, аккаунт работает" : `Токен сохранён, но не работает: ${u.last_error}`); reload(); }
          }}>{action.busy ? "Проверяем…" : "Сохранить и проверить"}</button>
        </Modal>
      )}
      {groupsOf && (
        <Modal title={`Сообщества, где «${groupsOf.name}» — администратор`} onClose={() => setGroupsOf(null)}>
          {groupsOf.groups_cache.length === 0 ? <Hint>Список пуст. Создайте группу в VK и нажмите «Проверить» у аккаунта.</Hint> : (
            <table><tbody>{groupsOf.groups_cache.map((g) => <tr key={g.id}><td><a href={`https://vk.com/${g.screen_name || "club" + g.id}`} target="_blank" rel="noreferrer">{g.name}</a></td><td className="muted small">ID {g.id}</td><td className="small">{g.members_count ?? "—"} участн.</td></tr>)}</tbody></table>
          )}
        </Modal>
      )}
    </>
  );
}
