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

function senderParts(sender: string) {
  const match = sender.match(/^\s*(.*?)\s*<([^<>]+)>\s*$/);
  if (!match) return { name: sender, address: "" };
  return { name: match[1] || match[2], address: match[2] };
}

function statusClass(status: string) {
  if (status === "pending") return "border-amber-200 bg-amber-50 text-amber-700";
  if (status === "draft_ready") return "border-blue-200 bg-blue-50 text-blue-700";
  if (status === "replied") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  return "";
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

      <section className="mb-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="Recherche et filtres">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Recherche et filtres</h2>
            <p className="mt-0.5 text-xs text-slate-500">Affinez la liste sans perdre le contexte.</p>
          </div>
          {hasFilters ? (
            <button
              type="button"
              onClick={resetFilters}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-slate-500 outline-none hover:bg-slate-100 hover:text-blue-700 focus-visible:ring-2 focus-visible:ring-blue-500/30"
            >
              <FilterX className="size-3.5" />
              Effacer
            </button>
          ) : null}
        </div>
        <div className="relative mb-4">
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
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <FilterField label="Catégorie">
            <Select value={filters.category} onValueChange={(value) => updateFilter("category", value)}>
              <SelectTrigger aria-label="Filtrer par catégorie"><SelectValue placeholder="Catégorie" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Toutes</SelectItem>
                {Object.entries(categories).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="Priorité">
            <Select value={filters.priority} onValueChange={(value) => updateFilter("priority", value)}>
              <SelectTrigger aria-label="Filtrer par priorité"><SelectValue placeholder="Priorité" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Toutes</SelectItem>
                <SelectItem value="3">Haute</SelectItem>
                <SelectItem value="2">Moyenne</SelectItem>
                <SelectItem value="1">Basse</SelectItem>
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="Statut">
            <Select value={filters.status} onValueChange={(value) => updateFilter("status", value)}>
              <SelectTrigger aria-label="Filtrer par statut"><SelectValue placeholder="Statut" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {Object.entries(statuses).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="Expéditeur">
            <Input value={filters.sender} onChange={(event) => updateFilter("sender", event.target.value)} placeholder="Nom ou adresse" aria-label="Filtrer par expéditeur" />
          </FilterField>
          <FilterField label="Du">
            <Input type="date" value={filters.dateFrom} onChange={(event) => updateFilter("dateFrom", event.target.value)} aria-label="Date de début" />
          </FilterField>
          <FilterField label="Au">
            <Input type="date" value={filters.dateTo} onChange={(event) => updateFilter("dateTo", event.target.value)} aria-label="Date de fin" />
          </FilterField>
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white" aria-live="polite">
        {!loading && !error && data && data.items.length > 0 ? (
          <div className="hidden grid-cols-[minmax(180px,0.9fr)_minmax(320px,2fr)_minmax(230px,auto)] gap-5 border-b border-slate-200 bg-slate-50/70 px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 sm:grid">
            <span>Expéditeur</span><span>Message</span><span className="text-right">État et date</span>
          </div>
        ) : null}
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
        {!loading && !error && data?.items.map((email) => {
          const sender = senderParts(email.sender);
          return (
          <Link
            key={email.id}
            href={`/inbox/threads/${email.thread_id}`}
            className="group relative block border-b border-slate-100 outline-none last:border-b-0 hover:bg-slate-50/80 focus-visible:bg-blue-50/60 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500/30"
            aria-label={`Ouvrir la conversation : ${email.subject || "Sans objet"}`}
          >
            <span className="absolute inset-y-3 left-0 w-0.5 rounded-r bg-blue-600 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
            <article className="grid gap-3 px-4 py-4 sm:grid-cols-[minmax(180px,0.9fr)_minmax(320px,2fr)_minmax(230px,auto)] sm:items-center sm:gap-5 sm:px-5">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900">{sender.name}</p>
              {sender.address ? <p className="mt-0.5 hidden truncate text-xs text-slate-500 xl:block">{sender.address}</p> : null}
              <p className="mt-1 text-xs text-slate-400 sm:hidden">{formatDate(email.received_at)}</p>
            </div>
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2">
                <p className="truncate text-sm font-medium text-slate-900">{email.subject || "Sans objet"}</p>
              </div>
              <p className="mt-1 truncate text-sm text-slate-500">{email.summary || email.body_text}</p>
              <div className="mt-2 flex flex-wrap gap-1.5 sm:hidden">
                {email.category ? <Badge>{categories[email.category] ?? email.category}</Badge> : null}
                <Badge className={statusClass(email.status)}>{statuses[email.status] ?? email.status}</Badge>
                <Badge className={email.priority === 3 ? "border-blue-200 bg-blue-50 text-blue-700" : ""}>{priorityLabel(email.priority)}</Badge>
              </div>
            </div>
            <div className="hidden min-w-0 text-right sm:block">
              <p className="text-xs font-medium text-slate-500">{formatDate(email.received_at)}</p>
              <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                {email.category ? <Badge>{categories[email.category] ?? email.category}</Badge> : null}
                <Badge className={statusClass(email.status)}>{statuses[email.status] ?? email.status}</Badge>
                <Badge className={email.priority === 3 ? "border-blue-200 bg-blue-50 text-blue-700" : ""}>
                  {priorityLabel(email.priority)}
                </Badge>
              </div>
            </div>
            </article>
          </Link>
          );
        })}
      </section>

      {!loading && !error && data && data.total > 0 ? (
        <div className="mt-4 flex flex-col gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
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

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1.5">
      <span className="block text-xs font-medium text-slate-600">{label}</span>
      {children}
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
