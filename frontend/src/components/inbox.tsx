"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  FilterX,
  Inbox as InboxIcon,
  LoaderCircle,
  RefreshCw,
  Search,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { EmailPage } from "@/types/api";

const LIMIT = 10;

const categories: Record<string, string> = {
  client: "Client",
  facture: "Facture",
  "rendez-vous": "Rendez-vous",
  newsletter: "Newsletter",
  "spam probable": "Spam probable",
  autre: "Autre",
};

const statuses: Record<string, string> = {
  pending: "À traiter",
  draft_ready: "Brouillon prêt",
  replied: "Répondu",
  ignored: "Ignoré",
};

type Filters = {
  category: string;
  priority: string;
  status: string;
  sender: string;
  dateFrom: string;
  dateTo: string;
};

const emptyFilters: Filters = {
  category: "all",
  priority: "all",
  status: "all",
  sender: "",
  dateFrom: "",
  dateTo: "",
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function priorityLabel(priority: number | null) {
  if (priority === 3) return "Haute";
  if (priority === 2) return "Moyenne";
  return "Basse";
}

export function Inbox() {
  const router = useRouter();
  const [data, setData] = useState<EmailPage | null>(null);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timeout);
  }, [searchInput]);

  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), limit: String(LIMIT) });
    if (search) params.set("search", search);
    if (filters.category !== "all") params.set("category", filters.category);
    if (filters.priority !== "all") params.set("priority", filters.priority);
    if (filters.status !== "all") params.set("status", filters.status);
    if (filters.sender.trim()) params.set("sender", filters.sender.trim());
    if (filters.dateFrom) params.set("date_from", `${filters.dateFrom}T00:00:00Z`);
    if (filters.dateTo) params.set("date_to", `${filters.dateTo}T23:59:59.999Z`);
    return params.toString();
  }, [filters, page, search]);

  const loadEmails = useCallback(async (signal: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/emails?${query}`, { signal });
      if (response.status === 401) {
        router.replace("/login?session=expired");
        return;
      }
      if (!response.ok) throw new Error("request_failed");
      setData(await response.json());
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError("Impossible de charger vos e-mails. Vérifiez la connexion au backend.");
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, [query, router]);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => void loadEmails(controller.signal), 0);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [loadEmails, reloadKey]);

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / LIMIT));
  const hasFilters = searchInput !== "" || Object.entries(filters).some(
    ([key, value]) => key === "sender" || key.startsWith("date") ? value !== "" : value !== "all",
  );

  function updateFilter<Key extends keyof Filters>(key: Key, value: Filters[Key]) {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  }

  function resetFilters() {
    setSearchInput("");
    setSearch("");
    setFilters(emptyFilters);
    setPage(1);
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Boîte de réception</h1>
          <p className="mt-1 text-sm text-slate-500">
            {data ? `${data.total} message${data.total > 1 ? "s" : ""}` : "Chargement de vos messages"}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => setReloadKey((value) => value + 1)}
          disabled={loading}
        >
          <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          Actualiser
        </Button>
      </div>

      <section className="mb-4 rounded-lg border border-slate-200 bg-white p-3 sm:p-4" aria-label="Filtres">
        <div className="relative mb-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <Input
            className="pl-9"
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Rechercher dans l’objet et le contenu…"
            aria-label="Rechercher les e-mails"
          />
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
          <Select value={filters.category} onValueChange={(value) => updateFilter("category", value)}>
            <SelectTrigger aria-label="Filtrer par catégorie"><SelectValue placeholder="Catégorie" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Toutes les catégories</SelectItem>
              {Object.entries(categories).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={filters.priority} onValueChange={(value) => updateFilter("priority", value)}>
            <SelectTrigger aria-label="Filtrer par priorité"><SelectValue placeholder="Priorité" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Toutes les priorités</SelectItem>
              <SelectItem value="3">Haute</SelectItem>
              <SelectItem value="2">Moyenne</SelectItem>
              <SelectItem value="1">Basse</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filters.status} onValueChange={(value) => updateFilter("status", value)}>
            <SelectTrigger aria-label="Filtrer par statut"><SelectValue placeholder="Statut" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les statuts</SelectItem>
              {Object.entries(statuses).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input
            value={filters.sender}
            onChange={(event) => updateFilter("sender", event.target.value)}
            placeholder="Expéditeur"
            aria-label="Filtrer par expéditeur"
          />
          <Input
            type="date"
            value={filters.dateFrom}
            onChange={(event) => updateFilter("dateFrom", event.target.value)}
            aria-label="Date de début"
          />
          <Input
            type="date"
            value={filters.dateTo}
            onChange={(event) => updateFilter("dateTo", event.target.value)}
            aria-label="Date de fin"
          />
        </div>
        {hasFilters ? (
          <button
            type="button"
            onClick={resetFilters}
            className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 outline-none hover:text-blue-700 focus-visible:text-blue-700"
          >
            <FilterX className="size-3.5" />
            Effacer les filtres
          </button>
        ) : null}
      </section>

      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white" aria-live="polite">
        {loading ? <LoadingRows /> : null}
        {!loading && error ? (
          <div className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
            <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-red-50 text-red-600">
              <AlertCircle className="size-5" />
            </span>
            <p className="font-medium text-slate-800">Chargement impossible</p>
            <p className="mt-1 max-w-md text-sm text-slate-500">{error}</p>
            <Button className="mt-4" variant="outline" onClick={() => setReloadKey((value) => value + 1)}>
              Réessayer
            </Button>
          </div>
        ) : null}
        {!loading && !error && data?.items.length === 0 ? (
          <div className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
            <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-slate-100 text-slate-500">
              <InboxIcon className="size-5" />
            </span>
            <p className="font-medium text-slate-800">Aucun e-mail trouvé</p>
            <p className="mt-1 text-sm text-slate-500">
              {hasFilters ? "Essayez de modifier vos critères de recherche." : "Votre boîte de réception est vide."}
            </p>
            {hasFilters ? <Button className="mt-4" variant="outline" onClick={resetFilters}>Réinitialiser</Button> : null}
          </div>
        ) : null}
        {!loading && !error && data?.items.map((email) => (
          <Link
            key={email.id}
            href={`/inbox/threads/${email.thread_id}`}
            className="block border-b border-slate-100 outline-none last:border-b-0 hover:bg-slate-50/80 focus-visible:bg-blue-50/60 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500/30"
            aria-label={`Ouvrir la conversation : ${email.subject || "Sans objet"}`}
          >
            <article className="grid gap-2 px-4 py-4 sm:grid-cols-[minmax(150px,0.8fr)_minmax(260px,2fr)_auto] sm:items-center sm:gap-5 sm:px-5">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-800">{email.sender}</p>
              <p className="mt-1 text-xs text-slate-400 sm:hidden">{formatDate(email.received_at)}</p>
            </div>
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2">
                <p className="truncate text-sm font-medium text-slate-900">{email.subject || "Sans objet"}</p>
                {email.category ? <Badge className="hidden shrink-0 lg:inline-flex">{categories[email.category] ?? email.category}</Badge> : null}
              </div>
              <p className="mt-1 truncate text-sm text-slate-500">{email.summary || email.body_text}</p>
              <div className="mt-2 flex flex-wrap gap-1.5 lg:hidden">
                {email.category ? <Badge>{categories[email.category] ?? email.category}</Badge> : null}
                <Badge>{statuses[email.status] ?? email.status}</Badge>
              </div>
            </div>
            <div className="hidden min-w-32 text-right sm:block">
              <p className="text-xs font-medium text-slate-500">{formatDate(email.received_at)}</p>
              <div className="mt-2 flex justify-end gap-1.5">
                <Badge className="hidden xl:inline-flex">{statuses[email.status] ?? email.status}</Badge>
                <Badge className={email.priority === 3 ? "border-blue-200 bg-blue-50 text-blue-700" : ""}>
                  {priorityLabel(email.priority)}
                </Badge>
              </div>
            </div>
            </article>
          </Link>
        ))}
      </section>

      {!loading && !error && data && data.total > 0 ? (
        <div className="mt-4 flex flex-col gap-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
          <p>
            {Math.min((page - 1) * LIMIT + 1, data.total)}–{Math.min(page * LIMIT, data.total)} sur {data.total}
          </p>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setPage((value) => value - 1)} disabled={page <= 1}>
              <ChevronLeft className="size-4" /> Précédent
            </Button>
            <span className="min-w-20 text-center text-xs font-medium text-slate-500">
              Page {page} / {totalPages}
            </span>
            <Button variant="outline" onClick={() => setPage((value) => value + 1)} disabled={page >= totalPages}>
              Suivant <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function LoadingRows() {
  return (
    <div aria-label="Chargement des e-mails">
      {[...Array(6)].map((_, index) => (
        <div key={index} className="grid gap-4 border-b border-slate-100 px-5 py-5 last:border-b-0 sm:grid-cols-[0.8fr_2fr_auto]">
          <div className="h-3.5 w-32 animate-pulse rounded bg-slate-100" />
          <div className="space-y-2">
            <div className="h-3.5 w-2/3 animate-pulse rounded bg-slate-100" />
            <div className="h-3 w-5/6 animate-pulse rounded bg-slate-100" />
          </div>
          <LoaderCircle className="hidden size-4 animate-spin text-slate-300 sm:block" />
        </div>
      ))}
    </div>
  );
}
