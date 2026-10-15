import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE, fetchBackend } from "@/lib/backend";

export async function POST() {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE)?.value;

  if (token) {
    try {
      await fetchBackend("/auth/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // The local session is still removed when the backend is unavailable.
    }
  }

  const response = new NextResponse(null, { status: 204 });
  response.cookies.delete(AUTH_COOKIE);
  return response;
}
