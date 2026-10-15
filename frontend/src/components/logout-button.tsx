"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle, LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";

export function LogoutButton({ compact = false }: { compact?: boolean }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function logout() {
    setLoading(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size={compact ? "icon" : "default"}
      className={compact ? "md:hidden" : "w-full justify-start"}
      onClick={logout}
      disabled={loading}
      aria-label="Se déconnecter"
    >
      {loading ? <LoaderCircle className="size-4 animate-spin" /> : <LogOut className="size-4" />}
      {compact ? null : "Se déconnecter"}
    </Button>
  );
}
