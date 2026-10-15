import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { AUTH_COOKIE, fetchBackend } from "@/lib/backend";
import type { User } from "@/types/api";

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(AUTH_COOKIE)?.value;
  if (!token) redirect("/login");

  let response: Response;
  try {
    response = await fetchBackend("/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    redirect("/login?service=unavailable");
  }
  if (!response.ok) redirect("/login?session=expired");
  const user: User = await response.json();

  return <AppShell user={user}>{children}</AppShell>;
}
