import { LightspeedSyncProvider } from '@/components/LightspeedSync';
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { LayoutDashboard, Package, Truck, RefreshCw, Settings, ChevronLeft, ChevronRight, Layers, Users, LogOut, User, Search, FolderTree, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const getNavItems = (isAdmin) => {
  const items = [
    { path: "/", label: "Dashboard", icon: LayoutDashboard },
    { path: "/products", label: "Products", icon: Package },
    { path: "/product-search", label: "Product Search", icon: Search },
    { path: "/suppliers", label: "Suppliers", icon: Truck },
    { path: "/sync", label: "Sync Jobs", icon: RefreshCw },
    { path: "/category-mapping", label: "Category Mapping", icon: FolderTree },
    { path: "/preprocessing", label: "Pre-Processing", icon: Zap },
    { path: "/export-review", label: "Export Review", icon: Layers },
    { path: "/settings", label: "Settings", icon: Settings },
  ];
  if (isAdmin) {
    items.push({ path: "/users", label: "Users", icon: Users });
  }
  return items;
};

export default function Layout({ user, onLogout }) {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const navItems = getNavItems(user?.role === "admin");

  return (
    <LightspeedSyncProvider><div className="flex h-screen bg-[#09090B] text-zinc-100 font-body">
      <aside
        className={cn(
          "flex flex-col border-r border-zinc-800 bg-[#09090B] transition-all duration-200 shrink-0",
          collapsed ? "w-16" : "w-56"
        )}
        data-testid="sidebar"
      >
        <div className="flex items-center h-14 px-4 border-b border-zinc-800">
          <Layers className="w-6 h-6 text-blue-500 shrink-0" strokeWidth={1.5} />
          {!collapsed && (
            <span className="ml-3 font-heading font-bold text-lg tracking-tight text-white whitespace-nowrap">
              SupplierHub
            </span>
          )}
        </div>

        <nav className="flex-1 py-4 space-y-0.5 px-2">
          {navItems.map((item) => {
            const isActive =
              item.path === "/"
                ? location.pathname === "/"
                : location.pathname.startsWith(item.path);
            return (
              <NavLink
                key={item.path}
                to={item.path}
                data-testid={`nav-${item.label.toLowerCase().replace(/\s/g, "-")}`}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 text-sm transition-colors rounded-sm",
                  isActive
                    ? "bg-blue-600/10 text-blue-400 border-l-2 border-blue-500"
                    : "text-zinc-400 hover:text-white hover:bg-zinc-800/50 border-l-2 border-transparent"
                )}
              >
                <item.icon className="w-4 h-4 shrink-0" strokeWidth={1.5} />
                {!collapsed && <span className="font-medium">{item.label}</span>}
              </NavLink>
            );
          })}
        </nav>

        {/* User section */}
        <div className="border-t border-zinc-800 p-3">
          {!collapsed ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 px-2">
                <div className="w-8 h-8 bg-zinc-800 rounded-full flex items-center justify-center border border-zinc-700">
                  <User className="w-4 h-4 text-zinc-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-zinc-200 truncate">{user?.name}</p>
                  <p className="text-xs text-zinc-500 truncate">@{user?.username}</p>
                </div>
              </div>
              <Button
                onClick={onLogout}
                variant="ghost"
                className="w-full justify-start text-zinc-400 hover:text-red-400 hover:bg-red-950/20 rounded-none text-sm"
                data-testid="logout-btn"
              >
                <LogOut className="w-4 h-4 mr-2" />
                Sign Out
              </Button>
            </div>
          ) : (
            <Button
              onClick={onLogout}
              variant="ghost"
              size="sm"
              className="w-full text-zinc-400 hover:text-red-400 hover:bg-red-950/20 rounded-none"
              data-testid="logout-btn"
              title="Sign Out"
            >
              <LogOut className="w-4 h-4" />
            </Button>
          )}
        </div>

        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center justify-center h-10 border-t border-zinc-800 text-zinc-500 hover:text-white transition-colors"
          data-testid="sidebar-toggle"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </aside>

      <main className="flex-1 overflow-auto pb-28">
        <Outlet />
      </main>
    </div></LightspeedSyncProvider>
  );
}


