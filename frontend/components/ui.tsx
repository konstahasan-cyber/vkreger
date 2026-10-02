"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { STATUS_LABELS } from "@/lib/format";
import type { Job } from "@/lib/types";

export function useLoad<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

/** Runs an async action, exposing busy/error/success state for buttons. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await fn();
      if (ok) setMessage(ok);
      return result;
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, message, run, setError, setMessage };
}

const OK = ["alive", "active", "published", "success", "sent", "won", "used"];
const ERR = ["dead", "invalid", "error", "failed", "rejected", "lost", "NEGATIVE", "SPAM"];
const WARN = ["warning", "scheduled", "pending_approval", "publishing", "running", "pending", "analyzing", "LEAD", "new"];

export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  const cls = OK.includes(value) ? "ok" : ERR.includes(value) ? "err" : WARN.includes(value) ? "warn" : "info";
  return <span className={`badge ${cls}`}>{STATUS_LABELS[value] || value}</span>;
}

export function Alerts({ error, message }: { error?: string | null; message?: string | null }) {
  return (
    <>
      {error && <div className="error-box">{error}</div>}
      {message && <div className="ok-box">{message}</div>}
    </>
  );
}

/** Polls a background job until it finishes. */
export function useJob(onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  const poll = useCallback((id: number) => {
    const tick = async () => {
      try {
        const current = await api<Job>(`/jobs/${id}`);
        setJob(current);
        if (current.status === "success" || current.status === "failed") {
          doneRef.current?.(current);
          return;
        }
      } catch {
        /* retry */
      }
      timer.current = setTimeout(tick, 1500);
    };
    tick();
  }, []);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const start = useCallback((j: Job) => { setJob(j); poll(j.id); }, [poll]);
  return { job, start };
}

export function JobStatus({ job }: { job: Job | null }) {
  if (!job) return null;
  return (
    <div className={job.status === "failed" ? "error-box" : job.status === "success" ? "ok-box" : "card small"}>
      Задача #{job.id} ({job.type}): <Badge value={job.status} />
      {job.status === "running" || job.status === "pending" ? " — AI работает, это может занять до минуты…" : ""}
      {job.error ? ` — ${job.error}` : ""}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="topbar"><h2 style={{ margin: 0 }}>{title}</h2><button onClick={onClose}>✕</button></div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="field"><label>{label}</label>{children}</div>;
}

/** Reads a query string parameter on the client (avoids Suspense requirements of useSearchParams). */
export function useQueryParam(name: string): [string, (v: string) => void, boolean] {
  const [value, setValue] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setValue(new URLSearchParams(window.location.search).get(name) || "");
    setReady(true);
  }, [name]);
  return [value, setValue, ready];
}

export function ProjectSelect({ value, onChange, allowAll = true }: { value: string; onChange: (v: string) => void; allowAll?: boolean }) {
  const { data } = useLoad<{ id: number; name: string }[]>("/projects");
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={{ width: 220 }}>
      {allowAll && <option value="">Все проекты</option>}
      {(data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
    </select>
  );
}
