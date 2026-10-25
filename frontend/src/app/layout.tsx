import type { Metadata, Viewport } from "next";

import "@fontsource-variable/dm-sans/wght.css";
import "@fontsource/cormorant-garamond/500.css";
import "@fontsource/cormorant-garamond/600.css";
import "@fontsource/cormorant-garamond/500-italic.css";
import "./globals.css";

import { Backdrop } from "@/components/brand/backdrop";
import { PwaRuntime } from "@/components/pwa/pwa-runtime";
import { Toaster } from "@/components/ui/toaster";
import { DEFAULT_APP_NAME } from "@/lib/app-name";

// Rendered per request so every page gets a fresh CSP nonce (src/proxy.ts).
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: DEFAULT_APP_NAME, template: `%s · ${DEFAULT_APP_NAME}` },
  description: "Now playing, shared.",
  applicationName: DEFAULT_APP_NAME,
  robots: { index: false, follow: false },
  manifest: "/manifest.webmanifest",
  referrer: "no-referrer",
  appleWebApp: { capable: true, title: DEFAULT_APP_NAME, statusBarStyle: "default" },
  formatDetection: { telephone: false, email: false, address: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#FFF9F5" },
    { media: "(prefers-color-scheme: dark)", color: "#1C1719" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="min-h-dvh">
        <Backdrop />
        {children}
        <Toaster />
        <PwaRuntime />
      </body>
    </html>
  );
}
