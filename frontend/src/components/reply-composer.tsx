"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Check, Clock3, LoaderCircle, RefreshCw, Send, Save } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Draft, DraftTone, Reply, ReplyStatus } from "@/types/api";

type StoredRequest = {
  replyId?: string;
  idempotencyKey: string;
  draftId: string;
  bodyText: string;
};

const statusDetails: Record<ReplyStatus, { label: string; className: string }> = {
  pending: { label: "Demande en attente", className: "border-amber-200 bg-amber-50 text-amber-700" },
  sending: { label: "Traitement en cours", className: "border-blue-200 bg-blue-50 text-blue-700" },
  sent: { label: "Envoyé", className: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  failed: { label: "Échec", className: "border-red-200 bg-red-50 text-red-700" },
};

async function errorMessage(response: Response) {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // The generic message below also covers non-JSON proxy errors.
  }
  return "Une erreur est survenue. Réessayez dans un instant.";
}

export function ReplyComposer({ emailId }: { emailId: string }) {
  const router = useRouter();
  const busyRef = useRef(false);
  const [bodyText, setBodyText] = useState("");
  const [tone, setTone] = useState<DraftTone>("neutre");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [reply, setReply] = useState<Reply | null>(null);
  const [storedRequest, setStoredRequest] = useState<StoredRequest | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const draftStorageKey = `mailflow:draft:${emailId}`;
  const replyStorageKey = `mailflow:reply:${emailId}`;
  const requestLocked = storedRequest !== null;

  const handleUnauthorized = useCallback((response: Response) => {
    if (response.status !== 401) return false;
    router.replace("/login?session=expired");
    return true;
  }, [router]);

  useEffect(() => {
    let cancelled = false;

    async function restore() {
      const draftId = window.localStorage.getItem(draftStorageKey);
      const rawRequest = window.localStorage.getItem(replyStorageKey);

      if (draftId) {
        try {
          const response = await fetch(`/api/drafts/${encodeURIComponent(draftId)}`);
          if (handleUnauthorized(response)) return;
          if (response.ok) {
            const restoredDraft: Draft = await response.json();
            if (!cancelled) {
              setDraft(restoredDraft);
              setBodyText(restoredDraft.body_text);
              setTone(restoredDraft.tone);
            }
          } else if (response.status === 404) {
            window.localStorage.removeItem(draftStorageKey);
          }
        } catch {
          if (!cancelled) setError("Impossible de récupérer le brouillon enregistré.");
        }
      }

      if (rawRequest) {
        try {
          const request: StoredRequest = JSON.parse(rawRequest);
          if (!request.idempotencyKey || !request.draftId || !request.bodyText) throw new Error();
          if (!cancelled) {
            setStoredRequest(request);
            setBodyText(request.bodyText);
          }
          if (request.replyId) {
            const response = await fetch(`/api/replies/${encodeURIComponent(request.replyId)}`);
            if (handleUnauthorized(response)) return;
            if (response.ok && !cancelled) setReply(await response.json());
            if (response.status === 404) {
              window.localStorage.removeItem(replyStorageKey);
              if (!cancelled) setStoredRequest(null);
            }
          }
        } catch {
          window.localStorage.removeItem(replyStorageKey);
        }
      }

      if (!cancelled) setRestoring(false);
    }

    void restore();
    return () => { cancelled = true; };
  }, [draftStorageKey, handleUnauthorized, replyStorageKey]);

  useEffect(() => {
    if (!reply || (reply.status !== "pending" && reply.status !== "sending")) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/replies/${encodeURIComponent(reply.id)}`);
        if (handleUnauthorized(response)) return;
        if (response.ok) setReply(await response.json());
      } catch {
        // Keep the last known status; the user can still refresh the page.
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [handleUnauthorized, reply]);

  async function persistDraft() {
    const normalizedBody = bodyText.trim();
    if (!normalizedBody) throw new Error("Rédigez une réponse avant d’enregistrer le brouillon.");

    const response = await fetch(
      draft ? `/api/drafts/${encodeURIComponent(draft.id)}` : `/api/emails/${encodeURIComponent(emailId)}/draft`,
      {
        method: draft ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body_text: normalizedBody, tone }),
      },
    );
    if (handleUnauthorized(response)) throw new Error("Votre session a expiré.");
    if (!response.ok) throw new Error(await errorMessage(response));

    const savedDraft: Draft = await response.json();
    setDraft(savedDraft);
    setBodyText(savedDraft.body_text);
    window.localStorage.setItem(draftStorageKey, savedDraft.id);
    return savedDraft;
  }

  async function runOnce(action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await action();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Une erreur est survenue.");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function saveDraft() {
    void runOnce(async () => {
      await persistDraft();
      setSaved(true);
    });
  }

  async function submitReply(request: StoredRequest) {
    window.localStorage.setItem(replyStorageKey, JSON.stringify(request));
    setStoredRequest(request);

    const response = await fetch(`/api/emails/${encodeURIComponent(emailId)}/reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirmed: true,
        idempotency_key: request.idempotencyKey,
        draft_id: request.draftId,
        body_text: request.bodyText,
      }),
    });
    if (handleUnauthorized(response)) throw new Error("Votre session a expiré.");
    if (!response.ok) throw new Error(await errorMessage(response));

    const createdReply: Reply = await response.json();
    const completedRequest = { ...request, replyId: createdReply.id };
    window.localStorage.setItem(replyStorageKey, JSON.stringify(completedRequest));
    setStoredRequest(completedRequest);
    setReply(createdReply);
    setConfirming(false);
  }

  function confirmReply() {
    void runOnce(async () => {
      const savedDraft = await persistDraft();
      const request: StoredRequest = {
        idempotencyKey: crypto.randomUUID(),
        draftId: savedDraft.id,
        bodyText: savedDraft.body_text,
      };
      await submitReply(request);
    });
  }

  function retryReply() {
    if (!storedRequest) return;
    void runOnce(() => submitReply(storedRequest));
  }

  const status = reply ? statusDetails[reply.status] : null;

  return (
    <section className="mt-5 rounded-lg border border-slate-200 bg-white p-4 sm:p-5" aria-labelledby="reply-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 id="reply-title" className="text-sm font-semibold text-slate-900">Rédiger une réponse</h2>
          <p className="mt-1 text-xs text-slate-500">L’envoi réel n’est pas encore activé.</p>
        </div>
        {status ? (
          <span className={`inline-flex w-fit items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium ${status.className}`}>
            {reply?.status === "failed" ? <AlertCircle className="size-3.5" /> : <Clock3 className="size-3.5" />}
            {status.label}
          </span>
        ) : null}
      </div>

      {restoring ? (
        <div className="mt-4 flex min-h-32 items-center justify-center text-sm text-slate-500">
          <LoaderCircle className="mr-2 size-4 animate-spin" /> Récupération du brouillon…
        </div>
      ) : (
        <>
          <label htmlFor="reply-body" className="sr-only">Contenu de la réponse</label>
          <textarea
            id="reply-body"
            value={bodyText}
            onChange={(event) => { setBodyText(event.target.value); setSaved(false); }}
            disabled={requestLocked || busy}
            placeholder="Écrivez votre réponse…"
            rows={7}
            className="mt-4 w-full resize-y rounded-md border border-slate-200 bg-white px-3 py-2.5 text-sm leading-6 text-slate-800 outline-none transition-colors placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10 disabled:bg-slate-50 disabled:text-slate-500"
          />

          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-600" htmlFor="reply-tone">Ton</label>
              <Select value={tone} onValueChange={(value) => { setTone(value as DraftTone); setSaved(false); }} disabled={requestLocked || busy}>
                <SelectTrigger id="reply-tone" className="w-32"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="formel">Formel</SelectItem>
                  <SelectItem value="neutre">Neutre</SelectItem>
                  <SelectItem value="court">Court</SelectItem>
                </SelectContent>
              </Select>
              {saved ? <span className="flex items-center gap-1 text-xs text-emerald-700"><Check className="size-3.5" /> Enregistré</span> : null}
            </div>
            {!requestLocked ? (
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" onClick={saveDraft} disabled={busy || !bodyText.trim()}>
                  <Save className="size-4" /> Enregistrer
                </Button>
                <Button type="button" onClick={() => setConfirming(true)} disabled={busy || !bodyText.trim()}>
                  <Send className="size-4" /> Demander l’envoi
                </Button>
              </div>
            ) : null}
          </div>
        </>
      )}

      {confirming && !requestLocked ? (
        <div className="mt-4 rounded-md border border-blue-200 bg-blue-50 p-3">
          <p className="text-sm font-medium text-slate-900">Confirmer la demande d’envoi ?</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            La demande sera enregistrée en attente. Aucun e-mail Gmail ne sera envoyé maintenant.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" onClick={confirmReply} disabled={busy}>
              {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Check className="size-4" />}
              Confirmer
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>Annuler</Button>
          </div>
        </div>
      ) : null}

      {reply?.status === "sending" ? (
        <p className="mt-3 text-xs leading-5 text-slate-500">
          Le traitement est en cours ou son résultat est encore incertain. Une nouvelle demande n’est pas créée.
        </p>
      ) : null}
      {reply?.status === "failed" ? (
        <div className="mt-3 flex flex-col gap-2 rounded-md border border-red-200 bg-red-50 p-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-medium text-red-800">La demande a échoué.</p>
            {reply.error_message ? <p className="mt-1 text-xs text-red-700">{reply.error_message}</p> : null}
          </div>
          <Button type="button" variant="outline" onClick={retryReply} disabled={busy}>
            <RefreshCw className={`size-4 ${busy ? "animate-spin" : ""}`} /> Réessayer
          </Button>
        </div>
      ) : null}
      {storedRequest && !reply ? (
        <div className="mt-3 flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-amber-800">Le résultat de la demande est inconnu. Réessayez avec la même référence.</p>
          <Button type="button" variant="outline" onClick={retryReply} disabled={busy}>
            <RefreshCw className={`size-4 ${busy ? "animate-spin" : ""}`} /> Réessayer
          </Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <AlertCircle className="mt-0.5 size-4 shrink-0" /> {error}
        </p>
      ) : null}
    </section>
  );
}
