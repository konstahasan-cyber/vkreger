"use client";

import { useState } from "react";
import { api, qs } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Account, Proxy } from "@/lib/types";
import { Alerts, Badge, Field, Modal, useAction, useLoad } from "@/components/ui";

interface ImportResult { created: number[]; skipped_duplicates: number; errors: { line: number; error: string }[] }

export default function ProxiesPage() {
  const [status, setStatus] = useState("");
  const { data: proxies, reload, error } = useLoad<Proxy[]>(`/proxies${qs({ status })}`, [status]);
  const { data: accounts } = useLoad<Account[]>("/accounts");
  const action = useAction();
  const [showImport, setShowImport] = useState(false);
  const [text, setText] = useState("");
  const [scheme, setScheme] = useState("http");
  const [result, setResult] = useState<ImportResult | null>(null);

  async function doImport() {
    const r = await action.run(() => api<ImportResult>("/proxies/import", { method: "POST", json: { text, default_scheme: scheme, check: true } }));
    if (r) { setResult(r); setText(""); setTimeout(reload, 3000); reload(); }
  }
  const act = async (fn: () => Promise<unknown>, ok: string) => { await action.run(fn, ok); reload(); };

  return (
    <>
      <div className="topbar">
        <div><h1>Прокси</h1><div className="page-sub">Сетевые адреса для ваших аккаунтов VK: один прокси — один аккаунт.</div></div>
        <div className="row">
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 160 }}>
            <option value="">Все</option><option value="alive">Работают</option><option value="dead">Не работают</option><option value="unknown">Не проверены</option>
          </select>
          <button onClick={() => act(() => api("/proxies/check-all", { method: "POST" }), "Проверка всех proxy запущена в фоне")}>Проверить все</button>
          <button className="primary" onClick={() => { setResult(null); setShowImport(true); }}>Импорт списком</button>
        </div>
      </div>
      <Alerts error={error || action.error} message={action.message} />
      <div className="card small muted">Привяжите прокси к аккаунту на странице «Аккаунты VK» или прямо в таблице. Если прокси перестал работать, аккаунт автоматически получит свободный. Аккаунт может работать и без прокси.</div>
      <div className="card table-wrap">
        <table>
          <thead><tr><th>#</th><th>Адрес</th><th>Пароль</th><th>Статус</th><th>Внешний IP / страна</th><th>Скорость</th><th>Аккаунт</th><th>Проверен</th><th /></tr></thead>
          <tbody>
            {(proxies || []).map((p) => (
              <tr key={p.id}>
                <td>{p.id}</td>
                <td><code>{p.scheme}://{p.username ? p.username + "@" : ""}{p.host}:{p.port}</code>{p.last_error && <div className="small muted">{p.last_error}</div>}</td>
                <td className="small">{p.password_masked || "—"}</td>
                <td><Badge value={p.status} /></td>
                <td>{p.external_ip || "—"}<div className="small muted">{p.country || ""} {p.country_code ? `(${p.country_code})` : ""}</div></td>
                <td>{p.latency_ms != null ? `${p.latency_ms} ms` : "—"}</td>
                <td>
                  <select value={p.account_id ?? ""} onChange={(e) => e.target.value && act(() => api(`/proxies/${p.id}/assign?account_id=${e.target.value}`, { method: "POST" }), "Привязан")}>
                    <option value="">{p.account_name || "свободен"}</option>
                    {(accounts || []).filter((a) => a.id !== p.account_id).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </select>
                </td>
                <td className="small">{fmtDate(p.last_checked_at)}</td>
                <td><div className="row">
                  <button className="small" disabled={action.busy} onClick={() => act(() => api(`/proxies/${p.id}/check`, { method: "POST" }), "Проверено")}>Проверить</button>
                  <button className="small danger" onClick={() => confirm("Удалить proxy?") && act(() => api(`/proxies/${p.id}`, { method: "DELETE" }), "Удалён")}>✕</button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
        {proxies && proxies.length === 0 && <p className="muted">Нет proxy.</p>}
      </div>
      {showImport && (
        <Modal title="Загрузить список прокси" onClose={() => setShowImport(false)}>
          <Alerts error={action.error} />
          <p className="small muted">По одному на строку. Форматы: IP:PORT, IP:PORT:LOGIN, IP:PORT:LOGIN:PASSWORD, LOGIN@IP, LOGIN:PASSWORD@IP:PORT, http://LOGIN:PASSWORD@IP:PORT, socks5://LOGIN@IP</p>
          <Field label="Схема по умолчанию (для строк без http:// / socks5://)">
            <select value={scheme} onChange={(e) => setScheme(e.target.value)}><option value="http">HTTP</option><option value="https">HTTPS</option><option value="socks5">SOCKS5</option></select>
          </Field>
          <Field label="Список"><textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} /></Field>
          {result && (
            <div className="ok-box">Добавлено: {result.created.length}, дубликатов: {result.skipped_duplicates}, ошибок: {result.errors.length}. Проверка запущена.
              {result.errors.map((e) => <div key={e.line} className="small">строка {e.line}: {e.error}</div>)}
            </div>
          )}
          <button className="primary" disabled={action.busy || !text.trim()} onClick={doImport}>Импортировать и проверить</button>
        </Modal>
      )}
    </>
  );
}
