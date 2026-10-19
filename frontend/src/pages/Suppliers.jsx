import { useState, useEffect, useCallback } from "react";
import axios from "../lib/axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Truck, Plus, Pencil, Trash2, CheckCircle2, XCircle, Loader2, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";

const API = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";

const ENDPOINT_STYLES = [
  {value:"athletic_knit",label:"Athletic Knit (PromoStandards)"},
  {value:"caldwell",label:"Caldwell Recognition (REST)"},
  { value: "ss", label: "S&S Activewear" },
  { value: "atc", label: "ATC / SanMar" },
  { value: "alphabroder", label: "alphabroder" },
  { value: "custom", label: "Custom (Manual URLs)" },
];

const emptyForm = { 
  supplier_name: "", 
  api_base_url: "", 
  account_number: "", 
  password: "", 
  media_password: "",
  endpoint_style: "",
  use_uat: false,
  services: {},
  bulk_data_url: ""
};

export default function Suppliers() {
  const [suppliers, setSuppliers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [testing, setTesting] = useState(null);
  const [testResults, setTestResults] = useState({});
  const [showAdvanced, setShowAdvanced] = useState(false);

  const fetch = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/suppliers`);
      setSuppliers(res.data.suppliers || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const handleSave = async () => {
    if (!form.supplier_name) {
      toast.error("Supplier name is required");
      return;
    }
    try {
      if (editing) {
        await axios.put(`${API}/suppliers/${editing}`, form);
        toast.success("Supplier updated");
      } else {
        await axios.post(`${API}/suppliers`, form);
        toast.success("Supplier created");
      }
      setDialogOpen(false);
      setEditing(null);
      setForm(emptyForm);
      fetch();
    } catch (e) {
      toast.error("Failed to save supplier");
    }
  };

  const handleEdit = (s) => {
    setEditing(s.id);
    setForm({
      supplier_name: s.supplier_name,
      api_base_url: s.api_base_url || "",
      account_number: s.account_number || "",
      password: "",
      media_password: "",
      endpoint_style: s.endpoint_style || "",
      use_uat: s.use_uat || false,
      services: s.services || {},
      bulk_data_url: s.bulk_data_url || ""
    });
    setShowAdvanced(s.endpoint_style === "custom" || Object.keys(s.services || {}).length > 0 || s.bulk_data_url);
    setDialogOpen(true);
  };

  const handleTestConnection = async (supplierId) => {
    setTesting(supplierId);
    try {
      const res = await axios.post(`${API}/suppliers/${supplierId}/test`);
      setTestResults(prev => ({ ...prev, [supplierId]: res.data }));
      if (res.data.success) {
        toast.success("Connection successful!");
      } else {
        toast.error(res.data.message || "Connection failed");
      }
    } catch (e) {
      setTestResults(prev => ({ ...prev, [supplierId]: { success: false, message: e.response?.data?.detail || "Test failed" } }));
      toast.error("Connection test failed");
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this supplier and all its products?")) return;
    try {
      await axios.delete(`${API}/suppliers/${id}`);
      toast.success("Supplier deleted");
      fetch();
    } catch (e) {
      toast.error("Failed to delete");
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="suppliers-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">Suppliers</h1>
          <p className="text-zinc-500 text-sm mt-1">Manage PromoStandards supplier connections</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={(o) => { setDialogOpen(o); if (!o) { setEditing(null); setForm(emptyForm); setShowAdvanced(false); } }}>
          <DialogTrigger asChild>
            <Button className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="add-supplier-btn">
              <Plus className="w-4 h-4 mr-2" />Add Supplier
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-zinc-900 border-zinc-800 rounded-sm max-w-xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="font-heading">{editing ? "Edit Supplier" : "Add Supplier"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Supplier Name *</label>
                <Input
                  value={form.supplier_name}
                  onChange={(e) => setForm({ ...form, supplier_name: e.target.value })}
                  className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                  placeholder="e.g. S&S Activewear"
                  data-testid="supplier-name-input"
                />
              </div>
              
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Supplier Type *</label>
                <Select value={form.endpoint_style} onValueChange={(v) => {setForm({ ...form, endpoint_style: v, services: {},api_base_url:v==='caldwell'?'https://caldwellrecognition.com':form.api_base_url });setShowAdvanced(v==='athletic_knit');}}>
                  <SelectTrigger className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm" data-testid="endpoint-style-select">
                    <SelectValue placeholder="Select supplier type..." />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-900 border-zinc-800">
                    {ENDPOINT_STYLES.map((s) => (
                      <SelectItem key={s.value} value={s.value} className="font-mono text-sm">{s.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-zinc-600 mt-1">This determines the API endpoint structure</p>
              </div>

              <div>
                <label className="text-xs text-zinc-500 mb-1 block">API Base URL *</label>
                <Input
                  value={form.api_base_url}
                  onChange={(e) => setForm({ ...form, api_base_url: e.target.value })}
                  className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                  placeholder={form.endpoint_style === "ss" ? "https://promostandards-ca.ssactivewear.com" : "https://edi.atc-apparel.com"}
                  data-testid="supplier-url-input"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">{form.endpoint_style==='caldwell'?'Customer login email':'Account ID / Number'}</label>
                  <Input
                    value={form.account_number}
                    onChange={(e) => setForm({ ...form, account_number: e.target.value })}
                    className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                    data-testid="supplier-account-input"
                  />
                </div>
                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">Password</label>
                  <Input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                    placeholder={editing ? "(unchanged)" : ""}
                    data-testid="supplier-password-input"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Media Password (if different)</label>
                <Input
                  type="password"
                  value={form.media_password}
                  onChange={(e) => setForm({ ...form, media_password: e.target.value })}
                  className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                  placeholder={editing ? "(unchanged)" : "Leave blank to use main password"}
                  data-testid="supplier-media-password-input"
                />
              </div>

              <div className="flex items-center gap-2">
                <Switch checked={form.use_uat} onCheckedChange={(v) => setForm({ ...form, use_uat: v })} data-testid="supplier-uat-switch" />
                <label className="text-sm text-zinc-400">Use UAT (Test) Environment</label>
              </div>

              {/* Advanced: Custom Service URLs */}
              <div className="border-t border-zinc-800 pt-4">
                <button 
                  type="button"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="flex items-center gap-2 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
                  data-testid="toggle-advanced-btn"
                >
                  {showAdvanced ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  {showAdvanced ? "Hide" : "Show"} Advanced Options (Custom Service URLs)
                </button>
                
                {showAdvanced && (
                  <div className="mt-4 space-y-3 p-3 bg-zinc-950/50 border border-zinc-800">
                    <p className="text-xs text-zinc-600">{form.endpoint_style==='athletic_knit'?'Enter the working Athletic Knit Product Data, Inventory and Media service URLs':'Override auto-generated endpoints with custom URLs (optional)'}</p>
                    
                    {/* Bulk Data URL */}
                    <div>
                      <label className="text-xs text-zinc-500 mb-1 block">Bulk Data API URL</label>
                      <Input
                        value={form.bulk_data_url || ""}
                        onChange={(e) => setForm({ ...form, bulk_data_url: e.target.value })}
                        className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-xs"
                        placeholder="e.g., https://edi.atc-apparel.com/bulk-data/BulkDataService.php"
                        data-testid="bulk-data-url-input"
                      />
                    </div>
                    
                    {["product_data", "inventory", "pricing", "media"].map((svc) => (
                      <div key={svc}>
                        <label className="text-xs text-zinc-500 mb-1 block capitalize">{svc.replace("_", " ")} URL</label>
                        <Input
                          value={form.services[svc] || ""}
                          onChange={(e) => setForm({ ...form, services: { ...form.services, [svc]: e.target.value } })}
                          className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-xs"
                          placeholder={`Leave blank for auto-discovery`}
                          data-testid={`service-${svc}-input`}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-none border-zinc-700 text-zinc-300" data-testid="cancel-supplier-btn">Cancel</Button>
                <Button onClick={handleSave} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="save-supplier-btn">
                  {editing ? "Update" : "Create"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array(3).fill(0).map((_, i) => <div key={i} className="h-20 bg-zinc-800/30 animate-pulse rounded-sm" />)}
        </div>
      ) : suppliers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
          <Truck className="w-12 h-12 mb-4 text-zinc-700" strokeWidth={1} />
          <p className="font-mono text-sm">NO SUPPLIERS CONFIGURED</p>
        </div>
      ) : (
        <div className="space-y-3" data-testid="suppliers-list">
          {suppliers.map((s) => (
            <Card key={s.id} className="bg-zinc-900/50 border-zinc-800 rounded-sm hover:border-zinc-700 transition-colors" data-testid={`supplier-card-${s.id}`}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-zinc-800 flex items-center justify-center border border-zinc-700">
                      <Truck className="w-5 h-5 text-blue-400" strokeWidth={1.5} />
                    </div>
                    <div>
                      <p className="font-medium text-zinc-200">{s.supplier_name}</p>
                      <div className="flex items-center gap-3 mt-0.5 flex-wrap">
                        <span className="text-xs font-mono text-zinc-500">{s.account_number || "No account"}</span>
                        {s.endpoint_style && (
                          <>
                            <span className="text-zinc-700">|</span>
                            <span className="text-xs font-mono text-blue-400">{ENDPOINT_STYLES.find(e => e.value === s.endpoint_style)?.label || s.endpoint_style}</span>
                          </>
                        )}
                        {s.api_base_url && (
                          <>
                            <span className="text-zinc-700">|</span>
                            <span className="text-xs font-mono text-zinc-500 truncate max-w-[200px]">{s.api_base_url}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <p className="text-xs text-zinc-500">Products</p>
                      <p className="font-mono text-sm tabular-nums">{s.products_count || 0}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-zinc-500">Last Sync</p>
                      <p className="text-xs font-mono text-zinc-400">{s.last_sync_time ? new Date(s.last_sync_time).toLocaleDateString() : "Never"}</p>
                    </div>
                    <span className={`px-2 py-0.5 text-xs font-mono border rounded-none ${s.status === "active" ? "bg-emerald-950/50 text-emerald-400 border-emerald-800" : "bg-zinc-800 text-zinc-500 border-zinc-700"}`}>
                      {s.status}
                    </span>
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      onClick={() => handleTestConnection(s.id)} 
                      disabled={testing === s.id}
                      className="text-zinc-400 hover:text-white rounded-none gap-1.5"
                      data-testid={`test-supplier-${s.id}`}
                    >
                      {testing === s.id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : testResults[s.id]?.success ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      ) : testResults[s.id] ? (
                        <XCircle className="w-4 h-4 text-red-400" />
                      ) : null}
                      Test
                    </Button>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" onClick={() => handleEdit(s)} className="text-zinc-400 hover:text-white rounded-none" data-testid={`edit-supplier-${s.id}`}>
                        <Pencil className="w-4 h-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(s.id)} className="text-zinc-400 hover:text-red-400 rounded-none" data-testid={`delete-supplier-${s.id}`}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
