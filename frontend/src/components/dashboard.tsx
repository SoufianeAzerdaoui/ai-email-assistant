"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  FileText,
  Inbox,
  LoaderCircle,
  MailOpen,
  RefreshCw,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { DailySummary } from "@/types/api";

function todayValue() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

const categoryLabels: Record<string, string> = {
  client: "Client",
  facture: "Facture",
  "rendez-vous": "Rendez-vous",
  newsletter: "Newsletter",
  "spam probable": "Spam probable",
  autre: "Autre",
};

function priorityLabel(priority: number | null) {
  if (priority === 3) return "Priorité haute";
  if (priority === 2) return "Priorité moyenne";
  return "Priorité basse";
}

export function Dashboard() {
  const router = useRouter();
  const [date, setDate] = useState(todayValue);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const loadSummary = useCallback(async (signal: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/summary?date=${encodeURIComponent(date)}`, { signal });
      if (response.status === 401) {
        router.replace("/login?session=expired");
        return;
      }
      if (!response.ok) throw new Error("request_failed");
      setSummary(await response.json());
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError("Impossible de charger le résumé. Vérifiez la connexion au backend.");
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, [date, router]);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => void loadSummary(controller.signal), 0);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [loadSummary, reloadKey]);

  const stats = summary ? [
    { label: "Reçus", value: summary.total_emails, icon: MailOpen },
    { label: "À traiter", value: summary.pending_emails, icon: AlertCircle },
    { label: "Répondus", value: summary.replied_emails, icon: CheckCircle2 },
    { label: "Brouillons prêts", value: summary.draft_ready_emails, icon: FileText },
  ] : [];

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Dashboard</h1>
          <p className="mt-1 text-sm capitalize text-slate-500">{formatDate(date)}</p>
        </div>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <Input
            type="date"
            value={date}
            onChange={(event) => {
              if (event.target.value) setDate(event.target.value);
            }}
            aria-label="Choisir la date du résumé"
            className="min-w-0 sm:w-44"
          />
          {date !== todayValue() ? (
            <Button variant="outline" onClick={() => setDate(todayValue())}>Aujourd’hui</Button>
          ) : null}
          <Button
            size="icon"
            variant="outline"
            onClick={() => setReloadKey((value) => value + 1)}
            disabled={loading}
            aria-label="Actualiser le résumé"
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {loading ? <DashboardLoading /> : null}
      {!loading && error ? (
        <section className="flex min-h-80 flex-col items-center justify-center rounded-lg border border-slate-200 bg-white px-6 text-center">
          <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-red-50 text-red-600">
            <AlertCircle className="size-5" />
          </span>
          <p className="font-medium text-slate-800">Résumé indisponible</p>
          <p className="mt-1 max-w-md text-sm text-slate-500">{error}</p>
          <Button className="mt-4" variant="outline" onClick={() => setReloadKey((value) => value + 1)}>
            Réessayer
          </Button>
        </section>
      ) : null}
      {!loading && !error && summary ? (
        <div className="space-y-4">
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Statistiques du jour">
            {stats.map((stat) => {
              const Icon = stat.icon;
              return (
                <div key={stat.label} className="rounded-lg border border-slate-200 bg-white p-4 sm:p-5">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-medium text-slate-500">{stat.label}</p>
                    <span className="flex size-8 items-center justify-center rounded-md bg-slate-50 text-slate-500">
                      <Icon className="size-4" />
                    </span>
                  </div>
                  <p className="mt-4 text-3xl font-semibold tracking-tight text-slate-900">{stat.value}</p>
                </div>
              );
            })}
          </section>

          <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(280px,0.75fr)_minmax(0,1.7fr)]">
          <section className="rounded-lg border border-slate-200 bg-white p-5 sm:p-6">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Résumé quotidien</p>
            <p className="mt-4 text-[15px] leading-7 text-slate-700">{summary.daily_summary}</p>
          </section>

          <section className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-4 sm:px-5">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">E-mails prioritaires</h2>
                <p className="mt-0.5 text-xs text-slate-400">Les messages à traiter en premier</p>
              </div>
              <Badge>{summary.top_priority_emails.length} sur 5</Badge>
            </div>

            {summary.total_emails === 0 ? (
              <EmptyDay />
            ) : summary.top_priority_emails.length === 0 ? (
              <div className="flex min-h-48 flex-col items-center justify-center px-6 text-center">
                <span className="mb-3 flex size-9 items-center justify-center rounded-full bg-slate-100 text-slate-500">
                  <CheckCircle2 className="size-4" />
                </span>
                <p className="text-sm font-medium text-slate-800">Rien à traiter en priorité</p>
                <p className="mt-1 text-xs text-slate-500">Les messages de cette journée sont déjà traités.</p>
              </div>
            ) : (
              summary.top_priority_emails.map((email, index) => (
                <Link
                  key={email.id}
                  href={`/inbox/threads/${email.thread_id}`}
                  className="group relative grid gap-3 border-b border-slate-100 px-4 py-4 outline-none last:border-b-0 hover:bg-slate-50/80 focus-visible:bg-blue-50/60 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500/30 sm:grid-cols-[32px_minmax(140px,0.75fr)_minmax(220px,1.8fr)_auto] sm:items-center sm:px-5"
                  aria-label={`Ouvrir la conversation : ${email.subject || "Sans objet"}`}
                >
                  <span className="flex size-8 items-center justify-center rounded-md bg-blue-50 text-xs font-semibold text-blue-700">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-900">{email.sender}</p>
                    <p className="mt-0.5 text-xs text-slate-400">{formatTime(email.received_at)}</p>
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-slate-900">{email.subject || "Sans objet"}</p>
                      {email.category ? <Badge className="hidden shrink-0 lg:inline-flex">{categoryLabels[email.category] ?? email.category}</Badge> : null}
                      <Badge className={email.priority === 3 ? "shrink-0 border-blue-200 bg-blue-50 text-blue-700" : "shrink-0"}>
                        {priorityLabel(email.priority)}
                      </Badge>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-500">{email.reason}</p>
                  </div>
                  <ChevronRight className="hidden size-4 text-slate-300 transition-colors group-hover:text-blue-600 sm:block" />
                </Link>
              ))
            )}
          </section>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EmptyDay() {
  return (
    <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
      <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-slate-100 text-slate-500">
        <Inbox className="size-5" />
      </span>
      <p className="font-medium text-slate-800">Aucun e-mail ce jour-là</p>
      <p className="mt-1 text-sm text-slate-500">Choisissez une autre date pour consulter son activité.</p>
    </div>
  );
}

function DashboardLoading() {
  return (
    <div className="space-y-4" aria-label="Chargement du dashboard">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="rounded-lg border border-slate-200 bg-white p-5">
            <div className="h-3.5 w-20 animate-pulse rounded bg-slate-100" />
            <div className="mt-4 h-7 w-10 animate-pulse rounded bg-slate-100" />
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <div className="h-3 w-28 animate-pulse rounded bg-slate-100" />
        <div className="mt-4 h-3.5 w-3/4 animate-pulse rounded bg-slate-100" />
      </div>
      <div className="flex min-h-64 items-center justify-center rounded-lg border border-slate-200 bg-white">
        <LoaderCircle className="size-5 animate-spin text-slate-300" />
      </div>
    </div>
  );
}
