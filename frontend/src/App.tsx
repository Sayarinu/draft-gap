import { Navigate, Route, Routes } from "react-router-dom";
import Home from "./app/page";

export const App = () => {
  return (
    <main className="min-h-screen flex flex-col">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/upcoming-matches" element={<Navigate to="/" replace />} />
      </Routes>
    </main>
  );
};
