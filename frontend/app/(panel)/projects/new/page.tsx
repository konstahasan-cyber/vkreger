"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import ProjectForm from "@/components/ProjectForm";
import { Alerts, Hint, useAction } from "@/components/ui";

export default function NewProjectPage() {
  const router = useRouter();
  const action = useAction();
  return (
    <>
      <div className="small muted"><Link href="/projects">← Все проекты</Link></div>
      <h1>Новый проект</h1>
      <div className="page-sub">Шаг 1 из 2: расскажите о бизнесе. Дальше AI предложит оформление сообщества и стратегию.</div>
      <Hint>Обязательны только название проекта и бизнеса, но чем больше вы заполните, тем точнее будут посты. Всё можно поменять позже.</Hint>
      <Alerts error={action.error} />
      <ProjectForm submitLabel="Создать проект и перейти к запуску →" busy={action.busy} onSubmit={async (values) => {
        const p = await action.run(() => api<Project>("/projects", { method: "POST", json: values }));
        if (p) router.push(`/projects/${p.id}`);
      }} />
    </>
  );
}
