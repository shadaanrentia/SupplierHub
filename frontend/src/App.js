import "@/App.css";
import "@/lib/axios"; // Initialize axios interceptors
import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Products from "@/pages/Products";
import ProductDetail from "@/pages/ProductDetail";
import ProductSearch from "@/pages/ProductSearch";
import Suppliers from "@/pages/Suppliers";
import SyncManagement from "@/pages/SyncManagement";
import CategoryMapping from "@/pages/CategoryMapping";
import ProductPreprocessing from "@/pages/ProductPreprocessing";
import Settings from "@/pages/Settings";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ForgotPassword from "@/pages/ForgotPassword";
import Users from "@/pages/Users";
import ExportReview from "@/pages/ExportReview";

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedUser = localStorage.getItem("user");
    const token = localStorage.getItem("token");
    if (storedUser && token) {
      setUser(JSON.parse(storedUser));
    }
    setLoading(false);
  }, []);

  const handleLogin = (userData) => {
    setUser(userData);
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    setUser(null);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
      </div>
    );
  }

  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login onLogin={handleLogin} />} />
          <Route path="/register" element={user ? <Navigate to="/" replace /> : <Register />} />
          <Route path="/forgot-password" element={user ? <Navigate to="/" replace /> : <ForgotPassword />} />
          
          {/* Protected routes */}
          {user ? (
            <Route element={<Layout user={user} onLogout={handleLogout} />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/products" element={<Products />} />
              <Route path="/products/:id" element={<ProductDetail />} />
              <Route path="/product-search" element={<ProductSearch />} />
              <Route path="/suppliers" element={<Suppliers />} />
              <Route path="/sync" element={<SyncManagement />} />
              <Route path="/category-mapping" element={<CategoryMapping />} />
              <Route path="/export-review" element={<ExportReview />} />
              <Route path="/preprocessing" element={<ProductPreprocessing />} />
              <Route path="/settings" element={<Settings />} />
              {user.role === "admin" && <Route path="/users" element={<Users />} />}
            </Route>
          ) : (
            <Route path="*" element={<Navigate to="/login" replace />} />
          )}
          
          <Route path="*" element={<Navigate to={user ? "/" : "/login"} replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster theme="dark" position="top-right" richColors />
    </div>
  );
}

export default App;
