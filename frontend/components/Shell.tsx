"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, setToken } from "@/lib/api";

const NAV: { section: string; items: [string, string, string][] }[] = [
  { section: "Работа", items: [
    ["/", "🏠", "Главная"],
    ["/projects", "🚀", "Проекты"],
    ["/networks", "🔗", "Сеть групп"],
    ["/content", "📝", "Посты"],
    ["/calendar", "📅", "Календарь"],
    ["/messages", "💬", "Сообщения"],
    ["/leads", "🎯", "Заявки"],
    ["/analytics", "📊", "Аналитика"],
  ] },
  { section: "Подключения", items: [
    ["/accounts", "👤", "Аккаунты VK"],
    ["/communities", "👥", "Сообщества"],
    ["/proxies", "🌐", "Прокси"],
  ] },
  { section: "Система", items: [
    ["/ai-settings", "🤖", "Настройки AI"],
    ["/logs", "🧾", "Журнал"],
  ] },
];

const ROLES: Record<string, string> = { owner: "владелец", admin: "администратор", operator: "оператор", viewer: "наблюдатель" };

interface Me { email: string; role: string }

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api<Me>("/auth/me").then(setMe).catch(() => undefined);
  }, [router]);

  if (!me) return <div className="main muted">Загрузка…</div>;

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand"><img src="/logo.svg" alt="" width={32} height={32} style={{ borderRadius: 10 }} />VKreger</div>
        {NAV.map((group) => (
          <div key={group.section}>
            <div className="section">{group.section}</div>
            {group.items.map(([href, ico, label]) => (
              <Link key={href} href={href} className={isActive(href) ? "active" : ""}><span className="ico">{ico}</span>{label}</Link>
            ))}
          </div>
        ))}
        <div className="user">
          <div style={{ color: "#fff" }}>{me.email}</div>
          <div>{ROLES[me.role] || me.role}</div>
          <button className="small" style={{ marginTop: 10 }} onClick={() => { setToken(null); router.replace("/login"); }}>Выйти</button>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
