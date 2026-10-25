import { Suspense } from "react";

import { AppName } from "@/components/auth/app-name";
import { PublicFrame } from "@/components/auth/public-frame";
import { RedirectIfSignedIn } from "@/components/auth/redirect-if-signed-in";
import { WelcomeNotice } from "@/components/auth/welcome-notice";
import { LogoMark } from "@/components/brand/logo-mark";
import { ButtonLink } from "@/components/ui/button";

export default function Welcome() {
  return (
    <PublicFrame>
      <RedirectIfSignedIn />
      <div className="animate-fade-up text-center">
        <LogoMark className="mx-auto size-24" />
        <h1 className="mt-6 font-display text-[2.75rem] font-semibold leading-[1.02] sm:text-6xl">
          <AppName />
        </h1>
      </div>
      <Suspense>
        <WelcomeNotice />
      </Suspense>
      <div className="mt-10 flex flex-col gap-3">
        <ButtonLink href="/sign-in" size="lg">
          Sign in
        </ButtonLink>
      </div>
    </PublicFrame>
  );
}
