"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, Inbox, LoaderCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/components/user-provider";
import type { Thread } from "@/types/api";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "long",
    timeStyle: "short",
  }).format(new Date(value));
}

function isSentByUser(sender: string, email: string) {
  const normalizedSender = sender.trim().toLowerCase();
  const normalizedEmail = email.trim().toLowerCase();
  return normalizedSender === normalizedEmail || normalizedSender.includes(`<${normalizedEmail}>`);
}

export function Conversation({ threadId }: { threadId: string }) {
  const router = useRouter();
  const user = useCurrentUser();
  const [thread, setThread] = useState<Thread | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const loadThread = useCallback(async (signal: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/threads/${encodeURIComponent(threadId)}`, { signal });
      if (response.status === 401) {
        router.replace("/login?session=expired");
        return;
      }
      if (response.status === 404) {
        setError("Cette conversation est introuvable ou n’est plus accessible.");
        return;
      }
      if (!response.ok) throw new Error("request_failed");
      setThread(await response.json());
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError("Impossible de charger cette conversation. Vérifiez la connexion au backend.");
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, [router, threadId]);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => void loadThread(controller.signal), 0);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [loadThread, reloadKey]);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-5">
        <Link
          href="/inbox"
          className="-ml-3 mb-3 inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-slate-600 outline-none transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:ring-2 focus-visible:ring-blue-500/30"
        >
          <ArrowLeft className="size-4" />
          Retour à la boîte de réception
        </Link>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">
              {thread?.subject || (loading ? "Chargement…" : "Conversation")}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {thread ? `${thread.emails.length} message${thread.emails.length > 1 ? "s" : ""}` : "Fil de discussion"}
            </p>
          </div>
          {!loading && thread ? (
            <Button variant="outline" onClick={() => setReloadKey((value) => value + 1)}>
              <RefreshCw className="size-4" /> Actualiser
            </Button>
          ) : null}
        </div>
      </div>

      {loading ? <ConversationLoading /> : null}
      {!loading && error ? (
        <section className="flex min-h-72 flex-col items-center justify-center rounded-lg border border-slate-200 bg-white px-6 text-center">
          <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-red-50 text-red-600">
            <AlertCircle className="size-5" />
          </span>
          <p className="font-medium text-slate-800">Conversation indisponible</p>
          <p className="mt-1 max-w-md text-sm text-slate-500">{error}</p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            <Button variant="outline" onClick={() => setReloadKey((value) => value + 1)}>Réessayer</Button>
            <Button variant="ghost" onClick={() => router.push("/inbox")}>Retour à l’inbox</Button>
          </div>
        </section>
      ) : null}
      {!loading && !error && thread?.emails.length === 0 ? (
        <section className="flex min-h-72 flex-col items-center justify-center rounded-lg border border-slate-200 bg-white px-6 text-center">
          <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-slate-100 text-slate-500">
            <Inbox className="size-5" />
          </span>
          <p className="font-medium text-slate-800">Conversation vide</p>
          <p className="mt-1 text-sm text-slate-500">Aucun message n’est disponible dans ce fil.</p>
        </section>
      ) : null}
      {!loading && !error && thread && thread.emails.length > 0 ? (
        <div className="space-y-3">
          {thread.emails.map((message) => {
            const sent = isSentByUser(message.sender, user.email);
            return (
              <article
                key={message.id}
                className={`w-full rounded-lg border p-4 sm:p-5 ${
                  sent
                    ? "ml-auto border-blue-200 bg-blue-50/60 lg:max-w-[88%]"
                    : "mr-auto border-slate-200 bg-white lg:max-w-[88%]"
                }`}
              >
                <div className="flex items-start gap-3">
                  <span className={`flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                    sent ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-600"
                  }`}>
                    {message.sender.trim().slice(0, 1).toUpperCase() || "?"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <p className="truncate text-sm font-medium text-slate-900">
                            {sent ? "Vous" : message.sender}
                          </p>
                          {sent ? (
                            <span className="rounded-md border border-blue-200 bg-white/70 px-1.5 py-0.5 text-[11px] font-medium text-blue-700">
                              Envoyé
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-0.5 truncate text-xs text-slate-500">
                          À : {message.recipients.join(", ") || "Destinataire inconnu"}
                        </p>
                      </div>
                      <time dateTime={message.received_at} className="shrink-0 text-xs text-slate-400">
                        {formatDate(message.received_at)}
                      </time>
                    </div>
                    <div className="mt-4 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
                      {message.body_text || <span className="italic text-slate-400">Message sans contenu.</span>}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function ConversationLoading() {
  return (
    <div className="space-y-3" aria-label="Chargement de la conversation">
      {[0, 1, 2].map((item) => (
        <div key={item} className="rounded-lg border border-slate-200 bg-white p-5">
          <div className="flex gap-3">
            <div className="size-9 shrink-0 animate-pulse rounded-full bg-slate-100" />
            <div className="flex-1 space-y-3">
              <div className="flex justify-between gap-4">
                <div className="h-3.5 w-40 animate-pulse rounded bg-slate-100" />
                <LoaderCircle className="size-4 animate-spin text-slate-300" />
              </div>
              <div className="h-3 w-56 animate-pulse rounded bg-slate-100" />
              <div className="space-y-2 pt-2">
                <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
                <div className="h-3 w-4/5 animate-pulse rounded bg-slate-100" />
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
