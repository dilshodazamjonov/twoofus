import { AppShell } from "@/components/shell/app-shell";

export default function SignedInLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
