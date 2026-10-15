import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE, backendUnavailable, fetchBackend } from "@/lib/backend";

async function proxyDraft(id: string, token: string, init?: RequestInit) {
  try {
    const backendResponse = await fetchBackend(`/drafts/${encodeURIComponent(id)}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        ...init?.headers,
      },
    });
    return NextResponse.json(await backendResponse.json(), { status: backendResponse.status });
  } catch {
    return backendUnavailable();
  }
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = (await cookies()).get(AUTH_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "Non authentifié." }, { status: 401 });
  return proxyDraft((await params).id, token);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = (await cookies()).get(AUTH_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "Non authentifié." }, { status: 401 });
  return proxyDraft((await params).id, token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
  });
}
