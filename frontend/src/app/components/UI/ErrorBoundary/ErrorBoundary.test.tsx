import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

interface ThrowingChildProps {
  shouldThrow: boolean;
}

const ThrowingChild = ({ shouldThrow }: ThrowingChildProps) => {
  if (shouldThrow) {
    throw new Error("boom");
  }

  return <div>Recovered</div>;
};

const ThrowingStringChild = () => {
  throw "not-an-error-instance";
};

const ErrorBoundaryHarness = () => {
  const [shouldThrow, setShouldThrow] = useState(true);

  return (
    <>
      <button type="button" onClick={() => setShouldThrow(false)}>
        Resolve
      </button>
      <ErrorBoundary>
        <ThrowingChild shouldThrow={shouldThrow} />
      </ErrorBoundary>
    </>
  );
};

describe("ErrorBoundary", () => {
  it("shows fallback when the child throws a non-Error value", async () => {
    render(
      <ErrorBoundary>
        <ThrowingStringChild />
      </ErrorBoundary>,
    );

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
  });

  it("shows fallback UI and can recover after the error source is removed", async () => {
    render(<ErrorBoundaryHarness />);

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Recovered")).toBeInTheDocument();
  });
});
