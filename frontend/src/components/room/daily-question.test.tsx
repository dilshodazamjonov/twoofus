import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { clearMemberData } from "@/lib/resources";
import { fakeApi } from "@/test/api";

import { DailyQuestion } from "./daily-question";

const question = { day: "2026-10-26", question: "A song for a rainy day?", my_answer: null, partner_answer: null };

describe("DailyQuestion", () => {
  beforeEach(() => clearMemberData());

  it("shows the other answer only after answering", async () => {
    const user = userEvent.setup();
    const { calls } = fakeApi({
      "GET /api/v1/room/question": { body: question },
      "PUT /api/v1/room/question": { body: { ...question, my_answer: "Kettle Song", partner_answer: "Paper Lanterns" } },
    });
    render(<DailyQuestion myName="Dilshod" partnerName="Sam" />);
    expect(await screen.findByRole("heading", { name: "A song for a rainy day?" })).toBeInTheDocument();
    expect(screen.queryByText("Paper Lanterns")).toBeNull();

    await user.type(screen.getByLabelText("Your answer"), "  Kettle Song ");
    await user.click(screen.getByRole("button", { name: "Save answer" }));
    expect(await screen.findByText("Kettle Song")).toBeInTheDocument();
    expect(screen.getByText("Paper Lanterns")).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ answer: "Kettle Song" }),
    );

    await user.click(screen.getByRole("button", { name: "Edit your answer" }));
    expect(screen.getByLabelText("Your answer")).toHaveValue("Kettle Song");
  });
});
