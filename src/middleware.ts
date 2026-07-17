import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Protected routes: /dashboard/*
  if (pathname.startsWith('/dashboard')) {
    const token = request.cookies.get('cf_order_token')?.value;
    if (!token) {
      return NextResponse.redirect(new URL('/', request.url));
    }
  }

  // Allow /api/setup without auth
  if (pathname === '/api/setup') {
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*'],
};
