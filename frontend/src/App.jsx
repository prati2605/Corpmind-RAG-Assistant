import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import ChatPage from "./pages/Chat";
import DashboardPage from "./pages/Dashboard";
import LoginPage from "./pages/Login";
import RegisterPage from "./pages/Register";

// Less-used pages load on demand to keep the first load small.
const AdminPage = lazy(() => import("./pages/Admin"));
const DocumentsPage = lazy(() => import("./pages/Documents"));
const HistoryPage = lazy(() => import("./pages/History"));
const SettingsPage = lazy(() => import("./pages/Settings"));

function RequireAuth({ children, admin }) {
  const { status, isAdmin } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Loading label="Opening CorpMind…" />;
  if (status === "signed-out") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (admin && !isAdmin) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  const { status } = useAuth();
  return (
    <Suspense fallback={<Loading />}>
    <Routes>
      <Route path="/login" element={status === "signed-in" ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/register" element={status === "signed-in" ? <Navigate to="/" replace /> : <RegisterPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="chat/:conversationId" element={<ChatPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route
          path="admin"
          element={
            <RequireAuth admin>
              <AdminPage />
            </RequireAuth>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
  );
}
