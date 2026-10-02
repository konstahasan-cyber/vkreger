"use client";

import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import ProjectForm from "@/components/ProjectForm";
import { Alerts, useAction } from "@/components/ui";

export default function NewProjectPage() {
  const router = useRouter();
  const action = useAction();
  return (
    <>
      <h1>Новый проект</h1>
      <Alerts error={action.error} />
      <ProjectForm submitLabel="Создать проект" busy={action.busy} onSubmit={async (values) => {
        const p = await action.run(() => api<Project>("/projects", { method: "POST", json: values }));
        if (p) router.push(`/projects/${p.id}`);
      }} />
    </>
  );
}
