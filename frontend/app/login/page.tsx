"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="card" onSubmit={submit}>
        <div className="brand" style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 6 }}><img src="/logo.svg" alt="" width={36} height={36} /><h1 style={{ margin: 0 }}>VKreger</h1></div>
        <p className="muted">Вход в панель управления</p>
        {error && <div className="error-box">{error}</div>}
        <div className="field"><label>Email</label><input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></div>
        <div className="field"><label>Пароль</label><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></div>
        <button className="primary big" disabled={busy} style={{ width: "100%", justifyContent: "center" }}>{busy ? "Вход…" : "Войти"}</button>
      </form>
    </div>
  );
}
