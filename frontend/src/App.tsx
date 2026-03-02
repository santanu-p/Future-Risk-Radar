import { Routes, Route } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import RegionDetail from "./pages/RegionDetail";
import AlertsPage from "./pages/Alerts";
import ReportsPage from "./pages/Reports";
import DriftDashboard from "./pages/DriftDashboard";
import ExplainabilityPage from "./pages/Explainability";
import NewsFeedPage from "./pages/NewsFeed";
import Layout from "./components/Layout";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/region/:regionCode" element={<RegionDetail />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/drift" element={<DriftDashboard />} />
        <Route path="/explain" element={<ExplainabilityPage />} />
        <Route path="/explain/:regionCode" element={<ExplainabilityPage />} />
        <Route path="/news" element={<NewsFeedPage />} />
      </Route>
    </Routes>
  );
}
