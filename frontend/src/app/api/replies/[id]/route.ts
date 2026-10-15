import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE, backendUnavailable, fetchBackend } from "@/lib/backend";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = (await cookies()).get(AUTH_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "Non authentifié." }, { status: 401 });

  try {
    const backendResponse = await fetchBackend(`/replies/${encodeURIComponent((await params).id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    return NextResponse.json(await backendResponse.json(), { status: backendResponse.status });
  } catch {
    return backendUnavailable();
  }
}
