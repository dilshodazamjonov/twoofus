import { Suspense } from "react";

import { PublicFrame } from "@/components/auth/public-frame";
import { SignInForm } from "@/components/auth/sign-in-form";
import { LogoMark } from "@/components/brand/logo-mark";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <PublicFrame>
      <div className="text-center">
        <LogoMark className="mx-auto size-14" />
        <h1 className="mt-5 font-display text-[2.5rem] font-semibold leading-tight">Sign in</h1>
      </div>
      <div className="mt-8 rounded-[1.75rem] border border-line bg-surface p-5 shadow-card sm:p-6">
        <Suspense fallback={<Skeleton className="h-64" />}>
          <SignInForm />
        </Suspense>
      </div>
    </PublicFrame>
  );
}
