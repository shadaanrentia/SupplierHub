import React, { useState, useEffect, useCallback } from "react";
import axios from "../lib/axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Package, Truck, Check, ArrowUpRight, Layers, RefreshCw } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";

const API = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";
const COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4", "#EC4899", "#F97316", "#84CC16", "#14B8A6"];

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,setError]=useState('');

  const fetchStats = useCallback(async () => {
    setError('');
    try {
      const res = await axios.get(`${API}/dashboard/stats`);
      setStats(res.data);
    } catch (e) {
      setError('Could not load dashboard. Please retry.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  if (loading) {
    return (
      <div className="p-6 space-y-6" data-testid="dashboard-loading">
        <div className="h-10 w-48 bg-zinc-800/50 animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {Array(6).fill(0).map((_, i) => <div key={i} className="h-24 bg-zinc-800/50 animate-pulse rounded-sm" />)}
        </div>
      </div>
    );
  }

  const statCards = [
    { label: "Total Products", value: stats?.total_products || 0, icon: Package, color: "text-blue-400" },
    { label: "Ready for Lightspeed", value: stats?.ready_for_lightspeed || 0, icon: Check, color: "text-emerald-400" },
    { label: "Synced to Lightspeed", value: stats?.synced_to_lightspeed || 0, icon: ArrowUpRight, color: "text-amber-400" },
    { label: "Suppliers", value: stats?.total_suppliers || 0, icon: Truck, color: "text-sky-400" },
    { label: "Total Variants", value: stats?.total_variants || 0, icon: Layers, color: "text-violet-400" },
    { label: "Active Products", value: stats?.active_products || 0, icon: Package, color: "text-green-400" },
  ];

  return (
    <div className="p-6 space-y-6" data-testid="dashboard-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-zinc-500 text-sm mt-1 font-body">Supplier catalogue and Lightspeed export overview</p>
        </div>
        <Button onClick={fetchStats} variant="outline" className="rounded-none border-zinc-700 text-zinc-300 hover:bg-zinc-800" data-testid="refresh-stats-btn">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {error && <div role="alert" className="border border-red-900 bg-red-950/30 p-3 text-red-300">{error}</div>}
      <div className="flex flex-wrap gap-3 text-sm">
        <a href="/preprocessing" className="border border-zinc-700 rounded px-3 py-2">Pre-processing</a>
        <a href="/export-review" className="border border-zinc-700 rounded px-3 py-2">Needs review: {stats?.review_products ?? '—'}</a>
        <span className="border border-amber-900 rounded px-3 py-2 text-amber-300">Images pending: {stats?.images_pending_lightspeed ?? '—'}</span>
        <span className="border border-red-900 rounded px-3 py-2 text-red-300">Failed exports: {stats?.failed_lightspeed ?? '—'}</span>
      </div>
      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {statCards.map((card, i) => (
          <Card key={i} className="bg-zinc-900/50 border-zinc-800 rounded-sm" data-testid={`stat-card-${i}`}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <card.icon className={`w-4 h-4 ${card.color}`} strokeWidth={1.5} />
              </div>
              <div className="font-mono text-2xl font-bold tabular-nums">{card.value.toLocaleString()}</div>
              <div className="text-xs text-zinc-500 mt-1 font-body">{card.label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Products by Category */}
        <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
          <CardHeader className="pb-2 border-b border-zinc-800/50 p-4">
            <CardTitle className="font-heading text-sm font-bold tracking-wider uppercase text-zinc-400">Products by Category</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            {stats?.category_distribution?.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={stats.category_distribution.slice(0, 8)} layout="vertical">
                  <XAxis type="number" tick={{ fill: "#71717A", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="category" tick={{ fill: "#71717A", fontSize: 9, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} width={80} />
                  <Tooltip contentStyle={{ background: "#18181B", border: "1px solid #27272A", borderRadius: 0, fontFamily: "Manrope", fontSize: 12 }} />
                  <Bar dataKey="count" fill="#3B82F6" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-zinc-600 text-sm font-mono">NO DATA</div>
            )}
          </CardContent>
        </Card>

        {/* Products by Brand */}
        <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
          <CardHeader className="pb-2 border-b border-zinc-800/50 p-4">
            <CardTitle className="font-heading text-sm font-bold tracking-wider uppercase text-zinc-400">Products by Brand</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            {stats?.brand_distribution?.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie 
                    data={stats.brand_distribution.slice(0, 8)} 
                    dataKey="count" 
                    nameKey="brand" 
                    cx="50%" 
                    cy="50%" 
                    outerRadius={70} 
                    label={({ brand, percent }) => `${brand} (${(percent * 100).toFixed(0)}%)`} 
                    labelLine={false}
                  >
                    {stats.brand_distribution.slice(0, 8).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#18181B", border: "1px solid #27272A", borderRadius: 0 }} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-zinc-600 text-sm font-mono">NO DATA</div>
            )}
          </CardContent>
        </Card>

        {/* Products by Supplier */}
        <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
          <CardHeader className="pb-2 border-b border-zinc-800/50 p-4">
            <CardTitle className="font-heading text-sm font-bold tracking-wider uppercase text-zinc-400">Products by Supplier</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            {stats?.supplier_distribution?.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie 
                    data={stats.supplier_distribution} 
                    dataKey="count" 
                    nameKey="supplier" 
                    cx="50%" 
                    cy="50%" 
                    innerRadius={40}
                    outerRadius={70} 
                    label={({ supplier, percent }) => `${supplier} (${(percent * 100).toFixed(0)}%)`} 
                    labelLine={false}
                  >
                    {stats.supplier_distribution.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#18181B", border: "1px solid #27272A", borderRadius: 0 }} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-zinc-600 text-sm font-mono">NO DATA</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
