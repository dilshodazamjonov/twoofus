import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Artwork } from "./artwork";

describe("Artwork", () => {
  it("shows the provider's image as delivered, without a referrer", () => {
    render(<Artwork src="https://i.scdn.co/image/abc" alt="Cover of Small Hours" />);
    const image = screen.getByRole("img", { name: "Cover of Small Hours" });
    expect(image.tagName).toBe("IMG");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image).toHaveClass("object-contain"); // never cropped
  });

  it("falls back to a quiet placeholder when there is no artwork", () => {
    render(<Artwork src={null} alt="Cover of Small Hours" />);
    const placeholder = screen.getByRole("img", { name: "Cover of Small Hours" });
    expect(placeholder.tagName).toBe("DIV");
  });

  it("falls back to the placeholder when the image fails to load, and tries a new one again", () => {
    const { rerender } = render(<Artwork src="https://i.scdn.co/image/broken" alt="Cover" />);
    fireEvent.error(screen.getByRole("img", { name: "Cover" }));
    expect(screen.getByRole("img", { name: "Cover" }).tagName).toBe("DIV");
    rerender(<Artwork src="https://i.scdn.co/image/next-song" alt="Cover" />);
    expect(screen.getByRole("img", { name: "Cover" }).tagName).toBe("IMG");
  });
});
