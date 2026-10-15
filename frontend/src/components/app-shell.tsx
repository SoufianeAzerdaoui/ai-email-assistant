import { Mail } from "lucide-react";

import { LogoutButton } from "@/components/logout-button";
import { ShellNavigation, ShellPageTitle } from "@/components/shell-navigation";
import { UserProvider } from "@/components/user-provider";
import type { User } from "@/types/api";

export function AppShell({ children, user }: { children: React.ReactNode; user: User }) {
  const initial = user.email.slice(0, 1).toUpperCase();

  return (
    <UserProvider user={user}>
      <div className="min-h-screen bg-slate-50 md:grid md:grid-cols-[240px_1fr]">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 border-r border-slate-200 bg-white md:flex md:flex-col">
        <div className="flex h-16 items-center gap-2.5 border-b border-slate-100 px-5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Mail className="size-4.5" strokeWidth={1.8} />
          </span>
          <span className="font-semibold tracking-tight text-slate-900">Mailflow</span>
        </div>
        <div className="flex-1 px-3 py-5">
          <p className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Navigation
          </p>
          <ShellNavigation />
        </div>
        <div className="border-t border-slate-100 p-3">
          <div className="mb-2 flex items-center gap-3 rounded-md px-2 py-2">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">
              {initial}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-800">{user.email}</p>
              <p className="text-xs text-slate-400">{user.is_admin ? "Administrateur" : "Utilisateur"}</p>
            </div>
          </div>
          <LogoutButton />
        </div>
      </aside>

      <div className="md:col-start-2">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-slate-200 bg-white/95 px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-2.5 md:hidden">
            <span className="flex size-8 items-center justify-center rounded-lg bg-blue-600 text-white">
              <Mail className="size-4" />
            </span>
            <span className="font-semibold text-slate-900">Mailflow</span>
          </div>
          <ShellPageTitle />
          <div className="flex items-center gap-2">
            <ShellNavigation compact />
            <LogoutButton compact />
          </div>
        </header>
        <main>{children}</main>
      </div>
      </div>
    </UserProvider>
  );
}
