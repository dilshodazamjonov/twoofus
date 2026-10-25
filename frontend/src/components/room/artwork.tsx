"use client";

import { Music2 } from "lucide-react";
import { useState } from "react";

import { cn } from "@/components/ui/cn";

/**
 * Album artwork, shown exactly as delivered: never cropped (object-contain),
 * overlaid, blurred or animated (Spotify's artwork rules), with 4 px corners
 * on phones and 8 px on large screens. Loaded straight from the provider's
 * CDN without a referrer; the service worker never caches it.
 */
export function Artwork({ src, alt, className }: { src: string | null; alt: string; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  const showImage = src !== null && failed !== src;
  return (
    <div
      className={cn(
        "relative aspect-square shrink-0 overflow-hidden rounded-[4px] bg-surface-2 shadow-soft ring-1 ring-line lg:rounded-[8px]",
        className,
      )}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- third-party artwork must not be proxied, resized or cached by our server
        <img
          src={src}
          alt={alt}
          referrerPolicy="no-referrer"
          loading="lazy"
          decoding="async"
          onError={() => setFailed(src)}
          className="size-full object-contain"
        />
      ) : (
        <div
          className="flex size-full items-center justify-center bg-accent-soft/60 text-accent-text"
          role={alt ? "img" : undefined}
          aria-label={alt || undefined}
          aria-hidden={alt ? undefined : true}
        >
          <Music2 aria-hidden className="size-1/3 opacity-70" />
        </div>
      )}
    </div>
  );
}
