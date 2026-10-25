import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { sessionResource } from "@/lib/resources";
import { fakeApi } from "@/test/api";
import { nav, router } from "@/test/navigation-mock";

import { SignInForm } from "./sign-in-form";

const anonymous = { authenticated: false, csrf_token: "t", user: null, session_expires_at: null };
const signedIn = {
  authenticated: true,
  csrf_token: "t2",
  user: { id: "1", username: "alex", display_name: "Alex", role: "owner" },
  session_expires_at: "2026-11-24T12:00:00Z",
};

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "alex");
  await user.type(screen.getByLabelText("Password"), "correct horse battery");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("SignInForm", () => {
  beforeEach(() => {
    sessionResource.reset();
    router.replace.mockClear();
    nav.search = new URLSearchParams();
  });

  it("explains wrong credentials without saying which part was wrong", async () => {
    fakeApi({
      "GET /api/v1/auth/session": { body: anonymous },
      "POST /api/v1/auth/login": { status: 401, body: { error: { code: "invalid_credentials", message: "Wrong username or password." } } },
    });
    render(<SignInForm />);
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("That username and password don't match.");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("tells how long to wait when rate limited", async () => {
    fakeApi({
      "GET /api/v1/auth/session": { body: anonymous },
      "POST /api/v1/auth/login": {
        status: 429,
        body: { error: { code: "rate_limited", message: "Too many attempts." } },
        headers: { "Retry-After": "120" },
      },
    });
    render(<SignInForm />);
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Please wait about 2 minutes");
  });

  it("signs in and goes to a safe `next` page only", async () => {
    nav.search = new URLSearchParams({ next: "https://evil.example/room" });
    const { calls } = fakeApi({
      "GET /api/v1/auth/session": { body: anonymous },
      "POST /api/v1/auth/login": { body: signedIn },
    });
    render(<SignInForm />);
    await fillAndSubmit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/room"));
    expect(calls.find((c) => c.path === "/api/v1/auth/login")?.body).toEqual({
      username: "alex",
      password: "correct horse battery",
    });
  });

  it("explains an expired session gently", () => {
    nav.search = new URLSearchParams({ expired: "1" });
    fakeApi({ "GET /api/v1/auth/session": { body: anonymous } });
    render(<SignInForm />);
    expect(screen.getByText("Please sign in again")).toBeInTheDocument();
  });

  it("explains a brand-new install that has no account yet", async () => {
    fakeApi({
      "GET /api/v1/auth/session": { body: anonymous },
      "GET /api/v1/setup/status": { body: { owner_exists: false } },
    });
    render(<SignInForm />);
    expect(await screen.findByText("Not set up yet")).toBeInTheDocument();
  });

  it("says nothing about setup once the owner exists", async () => {
    const { calls } = fakeApi({
      "GET /api/v1/auth/session": { body: anonymous },
      "GET /api/v1/setup/status": { body: { owner_exists: true } },
    });
    render(<SignInForm />);
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/setup/status")).toBe(true));
    expect(screen.queryByText("Not set up yet")).not.toBeInTheDocument();
  });
});
