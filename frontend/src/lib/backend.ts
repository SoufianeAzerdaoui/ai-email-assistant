import "server-only";

export const AUTH_COOKIE = "email_assistant_session";

export function backendUrl(path: string) {
  const baseUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  return new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
}

export async function fetchBackend(path: string, init?: RequestInit) {
  return fetch(backendUrl(path), {
    ...init,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
}

export function backendUnavailable() {
  return Response.json(
    { detail: "Le service de messagerie est temporairement indisponible." },
    { status: 502 },
  );
}
