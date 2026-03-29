import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: unknown | null;
}

function messageFromUnknown(error: unknown | null): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  if (error === undefined) {
    return "undefined";
  }
  if (error === null) {
    return "null";
  }
  try {
    const serialized = JSON.stringify(error);
    if (typeof serialized === "string") {
      return serialized;
    }
  } catch {
  }
  return String(error);
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: unknown, errorInfo: ErrorInfo): void {
    if (import.meta.env.MODE !== "test") {
      console.error("[Draft Gap] ErrorBoundary caught:", error, errorInfo);
    }
  }

  render(): ReactNode {
    if (this.state.hasError) {
      const text = messageFromUnknown(this.state.error);
      const isNetwork =
        text.includes("fetch") ||
        text.includes("Network") ||
        text.includes("Backend not reachable");
      return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-concrete p-6">
          <h1 className="mb-2 text-lg font-semibold uppercase tracking-wide text-cream">
            Something went wrong
          </h1>
          <p className="mb-4 max-w-md text-center text-sm text-taupe">
            {isNetwork
              ? "Unable to reach the server. Check your connection and try again."
              : "An unexpected error occurred. Try refreshing the page."}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, error: null })}
            className="rounded border border-gold bg-gold/10 px-4 py-2 text-sm font-medium uppercase tracking-wide text-gold hover:bg-gold/20"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
