import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE, backendUnavailable, fetchBackend } from "@/lib/backend";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = (await cookies()).get(AUTH_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "Non authentifié." }, { status: 401 });

  const { id } = await params;
  try {
    const backendResponse = await fetchBackend(`/emails/${encodeURIComponent(id)}/draft`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: await request.text(),
    });
    return NextResponse.json(await backendResponse.json(), { status: backendResponse.status });
  } catch {
    return backendUnavailable();
  }
}
