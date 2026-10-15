import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE, backendUnavailable, fetchBackend } from "@/lib/backend";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = (await cookies()).get(AUTH_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "Non authentifié." }, { status: 401 });
  }

  const { id } = await params;
  try {
    const backendResponse = await fetchBackend(`/threads/${encodeURIComponent(id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const payload = await backendResponse.json();
    return NextResponse.json(payload, { status: backendResponse.status });
  } catch {
    return backendUnavailable();
  }
}
