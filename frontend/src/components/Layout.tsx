import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import Header from "./Header";
import AlertToast from "./AlertToast";

export default function Layout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <Header />
        <main className="relative flex-1">
          <Outlet />
        </main>
      </div>
      <AlertToast />
    </div>
  );
}
