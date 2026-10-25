import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { sessionResource } from "@/lib/resources";
import { fakeApi } from "@/test/api";
import { router } from "@/test/navigation-mock";

import { InviteAccept } from "./invite-accept";

const TOKEN = "abcdefghijklmnopqrstuvwxyz012345";
const anonymous = { authenticated: false, csrf_token: "t", user: null, session_expires_at: null };
const invitation = { app_name: "JustTheTwoOfUs", inviter_display_name: "Alex", expires_at: "2026-10-27T12:00:00Z" };

describe("InviteAccept", () => {
  beforeEach(() => {
    sessionResource.reset();
    router.replace.mockClear();
    window.location.hash = `#token=${TOKEN}`;
  });

  it("welcomes the invited person and validates before sending", async () => {
    const user = userEvent.setup();
    const { calls } = fakeApi({
      "GET /api/v1/auth/session": { body: anonymous },
      "POST /api/v1/invitations/inspect": { body: invitation },
      "POST /api/v1/invitations/accept": {
        status: 201,
        body: { authenticated: true, csrf_token: "x", user: { id: "2", username: "sam", display_name: "Sam", role: "partner" } },
      },
    });
    render(<InviteAccept />);
    expect(await screen.findByRole("heading", { name: "Alex invited you" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/invitations/inspect")?.body).toEqual({ token: TOKEN });

    await user.type(screen.getByLabelText("Your name"), "Sam");
    await user.type(screen.getByLabelText("Username"), "sam");
    await user.type(screen.getByLabelText("Password"), "a lovely long password");
    await user.type(screen.getByLabelText("Confirm password"), "a different password");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText("The passwords don't match.")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/v1/invitations/accept")).toBe(false);

    await user.clear(screen.getByLabelText("Confirm password"));
    await user.type(screen.getByLabelText("Confirm password"), "a lovely long password");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/connect"));
    expect(calls.find((c) => c.path === "/api/v1/invitations/accept")?.body).toEqual({
      token: TOKEN,
      username: "sam",
      display_name: "Sam",
      password: "a lovely long password",
    });
    expect(window.location.hash).toBe(""); // the used token leaves the address bar
  });

  it("handles an expired or used link gently", async () => {
    fakeApi({
      "GET /api/v1/auth/session": { body: anonymous },
      "POST /api/v1/invitations/inspect": {
        status: 400,
        body: { error: { code: "invitation_invalid", message: "This invitation link is invalid or has expired." } },
      },
    });
    render(<InviteAccept />);
    expect(await screen.findByText("This invitation can't be used")).toBeInTheDocument();
  });

  it("asks a signed-in visitor to sign out first", async () => {
    fakeApi({
      "GET /api/v1/auth/session": {
        body: { authenticated: true, csrf_token: "t", user: { id: "1", username: "alex", display_name: "Alex", role: "owner" } },
      },
      "POST /api/v1/invitations/inspect": { body: invitation },
    });
    render(<InviteAccept />);
    expect(await screen.findByText("You're signed in as Alex")).toBeInTheDocument();
  });

  it("explains an incomplete link", () => {
    window.location.hash = "";
    fakeApi({ "GET /api/v1/auth/session": { body: anonymous } });
    render(<InviteAccept />);
    expect(screen.getByText("This link looks incomplete")).toBeInTheDocument();
  });
});
