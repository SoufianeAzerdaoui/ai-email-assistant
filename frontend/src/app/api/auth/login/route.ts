import { NextResponse } from "next/server";

import { AUTH_COOKIE, backendUnavailable, fetchBackend } from "@/lib/backend";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Requête invalide." }, { status: 400 });
  }

  try {
    const backendResponse = await fetchBackend("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await backendResponse.json();
    if (!backendResponse.ok) {
      return NextResponse.json(payload, { status: backendResponse.status });
    }

    const response = NextResponse.json({ authenticated: true });
    response.cookies.set(AUTH_COOKIE, payload.access_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 60 * 60 * 24,
    });
    return response;
  } catch {
    return backendUnavailable();
  }
}
