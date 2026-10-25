import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearMemberData } from "@/lib/resources";
import { fakeApi } from "@/test/api";

import { YandexConnect, isYandexUrl } from "./yandex-connect";

const pending = {
  status: "pending",
  user_code: "ABCD-1234",
  verification_url: "https://ya.ru/device",
  expires_at: new Date(Date.now() + 300_000).toISOString(),
  poll_interval_seconds: 5,
  error_code: null,
};

describe("YandexConnect", () => {
  beforeEach(() => clearMemberData());
  afterEach(() => vi.useRealTimers());

  it("shows the code and Yandex's own page, then notices the approval", async () => {
    let polls = 0;
    fakeApi({
      "POST /api/v1/providers/yandex/device-authorization": { status: 201, body: pending },
      "POST /api/v1/providers/yandex/device-authorization/poll": () => {
        polls += 1;
        return { body: polls < 2 ? pending : { ...pending, status: "completed", user_code: null, verification_url: null } };
      },
      "GET /api/v1/providers": { body: { providers: [], connection: null, pending_authorization: null } },
    });
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<YandexConnect resume={false} />);

    await user.click(screen.getByRole("button", { name: "Get a code from Yandex" }));
    expect(await screen.findByLabelText("Code: A B C D - 1 2 3 4")).toHaveTextContent("ABCD-1234");
    const link = screen.getByRole("link", { name: /Open ya\.ru/ });
    expect(link).toHaveAttribute("href", "https://ya.ru/device");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(await screen.findByText("Connected to Yandex Music")).toBeInTheDocument();
  });

  it("explains an expired code and offers a new one", async () => {
    fakeApi({
      "POST /api/v1/providers/yandex/device-authorization/poll": {
        body: { ...pending, status: "expired", user_code: null, verification_url: null, error_code: "expired" },
      },
    });
    render(<YandexConnect resume />);
    expect(await screen.findByText(/That code expired before it was approved/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get a new code" })).toBeInTheDocument();
  });
});

describe("isYandexUrl", () => {
  it("accepts only https Yandex hosts", () => {
    expect(isYandexUrl("https://ya.ru/device")).toBe(true);
    expect(isYandexUrl("https://oauth.yandex.ru/device")).toBe(true);
    expect(isYandexUrl("http://ya.ru/device")).toBe(false);
    expect(isYandexUrl("https://ya.ru.evil.example/device")).toBe(false);
    expect(isYandexUrl("https://notyandex.ru/")).toBe(false);
    expect(isYandexUrl(null)).toBe(false);
  });
});
