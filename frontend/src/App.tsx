import { Routes, Route } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import RegionDetail from "./pages/RegionDetail";
import Layout from "./components/Layout";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/region/:regionCode" element={<RegionDetail />} />
      </Route>
    </Routes>
  );
}
