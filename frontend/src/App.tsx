import { Navigate, Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "./app/components/UI/ErrorBoundary/ErrorBoundary";
import Home from "./app/page";

export const App = () => {
  return (
    <ErrorBoundary>
      <main className="min-h-screen flex flex-col">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/upcoming-matches" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </ErrorBoundary>
  );
};
