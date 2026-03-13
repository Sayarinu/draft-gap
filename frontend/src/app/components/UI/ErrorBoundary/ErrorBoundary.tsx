import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("[Draft Gap] ErrorBoundary caught:", error, errorInfo);
  }

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      const isNetwork =
        this.state.error.message.includes("fetch") ||
        this.state.error.message.includes("Network") ||
        this.state.error.message.includes("Backend not reachable");
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
            className="rounded bg-gold px-4 py-2 text-sm font-medium uppercase tracking-wide text-deepdark hover:opacity-90"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
