import { cn } from "@/components/ui/cn";

/**
 * The official Spotify full logo (public/brand/spotify, unmodified), required
 * next to Spotify metadata and artwork. Black on light backgrounds, white on
 * dark ones, never narrower than 70 px.
 */
export function SpotifyLogo({ className, width = 84 }: { className?: string; width?: number }) {
  const height = Math.round((width * 225.25) / 823.46);
  return (
    <picture className={cn("inline-block shrink-0", className)}>
      <source srcSet="/brand/spotify/Full_Logo_White_RGB.svg" media="(prefers-color-scheme: dark)" />
      <img src="/brand/spotify/Full_Logo_Black_RGB.svg" alt="Spotify" width={Math.max(70, width)} height={height} />
    </picture>
  );
}
