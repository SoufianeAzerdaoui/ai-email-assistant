"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Inbox, LayoutDashboard } from "lucide-react";

import { cn } from "@/lib/utils";

const items = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/inbox", label: "Boîte de réception", icon: Inbox },
];

export function ShellNavigation({ compact = false }: { compact?: boolean }) {
  const pathname = usePathname();

  return (
    <nav
      className={compact ? "flex items-center gap-1 md:hidden" : "space-y-1"}
      aria-label="Navigation principale"
    >
      {items.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            aria-label={compact ? item.label : undefined}
            className={cn(
              "flex items-center rounded-md text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-blue-500/30",
              compact ? "size-9 justify-center" : "h-9 gap-3 px-3",
              active
                ? "bg-blue-50 text-blue-700"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
            )}
          >
            <Icon className="size-4" />
            {compact ? null : item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function ShellPageTitle() {
  const pathname = usePathname();
  const content = pathname.startsWith("/dashboard")
    ? ["Dashboard", "Votre activité quotidienne en un coup d’œil"]
    : pathname.includes("/threads/")
      ? ["Conversation", "Tous les messages du fil"]
      : ["Boîte de réception", "Tous vos messages, au même endroit"];

  return (
    <div className="hidden md:block">
      <p className="text-sm font-medium text-slate-900">{content[0]}</p>
      <p className="text-xs text-slate-400">{content[1]}</p>
    </div>
  );
}
