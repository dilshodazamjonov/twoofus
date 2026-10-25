import { Suspense } from "react";

import { ConnectView } from "@/components/connect/connect-view";

export const metadata = { title: "Music" };

export default function ConnectPage() {
  return (
    <Suspense>
      <ConnectView />
    </Suspense>
  );
}
