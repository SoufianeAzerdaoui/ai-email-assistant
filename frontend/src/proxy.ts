import { NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE } from "@/lib/backend";

export function proxy(request: NextRequest) {
  if (!request.cookies.has(AUTH_COOKIE)) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/inbox/:path*"],
};
