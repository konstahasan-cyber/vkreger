"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, setToken } from "@/lib/api";

const NAV = [
  ["/", "Dashboard"],
  ["/projects", "Projects"],
  ["/accounts", "VK Accounts"],
  ["/proxies", "Proxies"],
  ["/communities", "Communities"],
  ["/content", "Content"],
  ["/calendar", "Calendar"],
  ["/messages", "Messages"],
  ["/leads", "Leads"],
  ["/analytics", "Analytics"],
  ["/ai-settings", "AI Settings"],
  ["/logs", "System Logs"],
] as const;

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
        <div className="brand">VKreger</div>
        {NAV.map(([href, label]) => (
          <Link key={href} href={href} className={isActive(href) ? "active" : ""}>{label}</Link>
        ))}
        <div className="small muted" style={{ padding: "16px 10px 0" }}>{me.email}<br />роль: {me.role}</div>
        <button className="logout small" onClick={() => { setToken(null); router.replace("/login"); }}>Выйти</button>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
