import { vi } from "vitest";

export const router = { replace: vi.fn(), push: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() };
export const nav = { pathname: "/room", search: new URLSearchParams() };

export const navigation = {
  useRouter: () => router,
  usePathname: () => nav.pathname,
  useSearchParams: () => nav.search,
};
