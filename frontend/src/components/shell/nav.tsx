"use client";

import { Headphones, House, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/components/ui/cn";

const ITEMS = [
  { href: "/room", label: "Home", icon: House },
  { href: "/connect", label: "Music", icon: Headphones },
  { href: "/settings", label: "Settings", icon: SlidersHorizontal },
] as const;

function useActive() {
  const pathname = usePathname();
  return (href: string) => pathname === href || pathname.startsWith(`${href}/`);
}

export function TopNav() {
  const isActive = useActive();
  return (
    <nav aria-label="Main" className="hidden md:block">
      <ul className="flex items-center gap-1">
        {ITEMS.map(({ href, label, icon: Icon }) => (
          <li key={href}>
            <Link
              href={href}
              aria-current={isActive(href) ? "page" : undefined}
              className={cn(
                "inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-[0.95rem] font-medium transition-colors",
                isActive(href) ? "bg-accent-soft text-accent-text" : "text-muted hover:bg-surface-2 hover:text-ink",
              )}
            >
              <Icon aria-hidden className="size-4" />
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function BottomNav() {
  const isActive = useActive();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className="mx-auto grid max-w-md grid-cols-3">
        {ITEMS.map(({ href, label, icon: Icon }) => {
          const active = isActive(href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-16 flex-col items-center justify-center gap-1 text-xs font-medium transition-colors",
                  active ? "text-accent-text" : "text-muted",
                )}
              >
                <Icon aria-hidden className={cn("size-[1.35rem]", active && "fill-accent-soft")} strokeWidth={active ? 2.2 : 1.8} />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
