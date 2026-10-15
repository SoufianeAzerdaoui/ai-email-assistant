import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE, backendUnavailable, fetchBackend } from "@/lib/backend";

export async function GET(request: NextRequest) {
  const token = (await cookies()).get(AUTH_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "Non authentifié." }, { status: 401 });
  }

  const date = request.nextUrl.searchParams.get("date");
  if (!date) {
    return NextResponse.json({ detail: "La date est requise." }, { status: 422 });
  }

  try {
    const backendResponse = await fetchBackend(`/summary?date=${encodeURIComponent(date)}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const payload = await backendResponse.json();
    return NextResponse.json(payload, { status: backendResponse.status });
  } catch {
    return backendUnavailable();
  }
}
