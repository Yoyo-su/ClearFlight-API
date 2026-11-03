import { useEffect } from "react";
import { Route, Routes } from "react-router";

import { Layout, SearchForm } from "./components/Layout";
import { AirportPage } from "./pages/AirportPage";
import { HomePage } from "./pages/HomePage";

export function NotFoundPage() {
  useEffect(() => {
    document.title = "Page not found – ClearFlight";
  }, []);
  return (
    <Layout>
      <div className="container stack">
        <h1>Page not found</h1>
        <p>There’s nothing at this address.</p>
        <SearchForm id="notfound-search" visibleLabel />
      </div>
    </Layout>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/airport/:code" element={<AirportPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
