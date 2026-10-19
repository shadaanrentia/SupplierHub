import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Search,
  Package,
  ChevronLeft,
  ChevronRight,
  Grid3X3,
  List,
  DollarSign,
  Warehouse,
  Image as ImageIcon,
  Loader2,
  MoreVertical,
  Trash2,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";

const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
const API = `${BACKEND_URL}/api`;

const getProductImage = (product) => {
  const candidates = [
    product?.thumbnail,
    product?.image,
    product?.thumbnail_base64,
  ];
  for (const value of candidates) {
    if (!value) continue;
    const src = String(value).trim();
    if (!src) continue;
    if (src.startsWith("data:image/")) {
      return src;
    }
    if (src.startsWith("http://") || src.startsWith("https://")) {
      return `${API}/media_proxy?url=${encodeURIComponent(src)}`;
    }
    if (src.startsWith("/")) {
      return `${BACKEND_URL}${src}`;
    }
    return `${BACKEND_URL}/${src}`;
  }
  return null;
};

function ProductImage({
  product,
  className = "",
  fallbackIconSize = "w-8 h-8",
}) {
  const [imageFailed, setImageFailed] = useState(false);

  const imageUrl = getProductImage(product);

  useEffect(() => {
    setImageFailed(false);
  }, [imageUrl]);

  if (!imageUrl || imageFailed) {
    return (
      <div
        className={`absolute inset-0 flex items-center justify-center bg-zinc-800/50 ${className}`}
      >
        <Package
          className={`${fallbackIconSize} text-zinc-700`}
          strokeWidth={1}
        />
      </div>
    );
  }

  return (
    <img
      src={imageUrl}
      alt={product?.product_name || "Product"}
      className={className}
      loading="lazy"
      onError={() => {
        console.error("PRODUCT IMAGE FAILED:", {
          id: product?.id,
          sku: product?.supplier_sku,
          name: product?.product_name,
          originalUrl: product?.thumbnail || product?.image,
          proxyUrl: imageUrl,
        });
        setImageFailed(true);
      }}
    />
  );
}

export default function Products() {
  const navigate = useNavigate();

  const [products, setProducts] = useState([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [supplier, setSupplier] = useState("all");
  const [category, setCategory] = useState("all");
  const [brand, setBrand] = useState("all");
  const [selectedFilter, setSelectedFilter] = useState("all");
  const [odooSyncFilter, setOdooSyncFilter] = useState("all");

  const [suppliers, setSuppliers] = useState([]);
  const [categories, setCategories] = useState([]);
  const [brands, setBrands] = useState([]);

  const [viewMode, setViewMode] = useState("grid");
  const [syncing, setSyncing] = useState({});
  const [selectedProducts, setSelectedProducts] = useState(new Set());
  const [deleting, setDeleting] = useState(false);

  const fetchFilters = useCallback(async () => {
    try {
      const [suppliersResponse, categoriesResponse, brandsResponse] =
        await Promise.all([
          axios.get(`${API}/suppliers`),
          axios.get(`${API}/products/categories`),
          axios.get(`${API}/products/brands`),
        ]);

      setSuppliers(suppliersResponse.data.suppliers || []);
      setCategories(categoriesResponse.data.categories || []);
      setBrands(brandsResponse.data.brands || []);
    } catch (error) {
      console.error("Filter fetch error:", error);
    }
  }, []);

  const fetchProducts = useCallback(async () => {
    setLoading(true);

    try {
      const params = {
        page,
        limit: 20,
      };

      if (search.trim()) {
        params.search = search.trim();
      }

      if (supplier !== "all") {
        params.supplier_id = supplier;
      }

      if (category !== "all") {
        params.category = category;
      }

      if (brand !== "all") {
        params.brand = brand;
      }

      if (selectedFilter === "selected") {
        params.selected_for_odoo = true;
      }

      if (selectedFilter === "not_selected") {
        params.selected_for_odoo = false;
      }

      if (odooSyncFilter === "synced") {
        params.odoo_synced = true;
      }

      if (odooSyncFilter === "not_synced") {
        params.odoo_synced = false;
      }

      const response = await axios.get(`${API}/products`, {
        params,
      });

      setProducts(response.data.products || []);
      setTotal(response.data.total || 0);
      setPages(response.data.pages || 1);
    } catch (error) {
      console.error("Products fetch error:", error);
      toast.error(
        error.response?.data?.detail || "Failed to load products"
      );
    } finally {
      setLoading(false);
    }
  }, [
    page,
    search,
    supplier,
    category,
    brand,
    selectedFilter,
    odooSyncFilter,
  ]);

  useEffect(() => {
    fetchFilters();
  }, [fetchFilters]);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  const syncProduct = async (productId, type) => {
    const key = `${productId}-${type}`;

    setSyncing((previous) => ({
      ...previous,
      [key]: true,
    }));

    try {
      const response = await axios.post(
        `${API}/sync/product/${productId}/${type}`
      );

      if (response.data.success) {
        toast.success(response.data.message);
        fetchProducts();
      } else {
        toast.error(
          response.data.message || `${type} sync failed`
        );
      }
    } catch (error) {
      console.error(`Failed to sync ${type}:`, error);

      toast.error(
        error.response?.data?.detail ||
          `Failed to sync ${type}`
      );
    } finally {
      setSyncing((previous) => ({
        ...previous,
        [key]: false,
      }));
    }
  };

  const toggleSelection = async (productId, currentValue) => {
    try {
      await axios.post(
        `${API}/products/${productId}/select-for-odoo`,
        {
          product_id: productId,
          selected: !currentValue,
        }
      );

      setProducts((previous) =>
        previous.map((product) =>
          product.id === productId
            ? {
                ...product,
                selected_for_odoo: !currentValue,
              }
            : product
        )
      );

      toast.success(
        !currentValue
          ? "Selected for Odoo"
          : "Deselected from Odoo"
      );
    } catch (error) {
      console.error("Odoo selection error:", error);

      toast.error(
        error.response?.data?.detail ||
          "Failed to update selection"
      );
    }
  };

  const toggleLightspeedSelection = async (
    productId,
    currentValue
  ) => {
    try {
      await axios.post(
        `${API}/products/${productId}/select-for-lightspeed`,
        {
          product_id: productId,
          selected: !currentValue,
        }
      );

      setProducts((previous) =>
        previous.map((product) =>
          product.id === productId
            ? {
                ...product,
                selected_for_lightspeed: !currentValue,
              }
            : product
        )
      );

      toast.success(
        !currentValue
          ? "Selected for Lightspeed"
          : "Deselected from Lightspeed"
      );
    } catch (error) {
      console.error("Lightspeed selection error:", error);

      toast.error(
        error.response?.data?.detail ||
          "Failed to update selection"
      );
    }
  };

  const toggleProductSelect = (productId) => {
    setSelectedProducts((previous) => {
      const next = new Set(previous);

      if (next.has(productId)) {
        next.delete(productId);
      } else {
        next.add(productId);
      }

      return next;
    });
  };

  const selectAllProducts = () => {
    if (
      products.length > 0 &&
      selectedProducts.size === products.length
    ) {
      setSelectedProducts(new Set());
    } else {
      setSelectedProducts(
        new Set(products.map((product) => product.id))
      );
    }
  };

  const deleteSelectedProducts = async () => {
    if (selectedProducts.size === 0) {
      return;
    }

    const confirmed = window.confirm(
      `Delete ${selectedProducts.size} selected product(s)?`
    );

    if (!confirmed) {
      return;
    }

    setDeleting(true);

    try {
      await axios.post(`${API}/products/bulk-delete`, {
        product_ids: Array.from(selectedProducts),
      });

      toast.success(
        `Deleted ${selectedProducts.size} products`
      );

      setSelectedProducts(new Set());

      await fetchProducts();
    } catch (error) {
      console.error("Delete selected products error:", error);

      toast.error(
        error.response?.data?.detail ||
          "Failed to delete products"
      );
    } finally {
      setDeleting(false);
    }
  };

  const deleteAllProducts = async () => {
    const confirmed = window.confirm(
      `Are you sure you want to delete ALL ${total} products? This action cannot be undone.`
    );

    if (!confirmed) {
      return;
    }

    setDeleting(true);

    try {
      await axios.delete(`${API}/products/delete-all`);

      toast.success("All products deleted");

      setSelectedProducts(new Set());

      await fetchProducts();
    } catch (error) {
      console.error("Delete all products error:", error);

      toast.error(
        error.response?.data?.detail ||
          "Failed to delete all products"
      );
    } finally {
      setDeleting(false);
    }
  };

  const handleSearch = (event) => {
    event.preventDefault();

    if (page !== 1) {
      setPage(1);
    } else {
      fetchProducts();
    }
  };

  const handleSupplierChange = (value) => {
    setSupplier(value);
    setPage(1);
  };

  const handleCategoryChange = (value) => {
    setCategory(value);
    setPage(1);
  };

  const handleBrandChange = (value) => {
    setBrand(value);
    setPage(1);
  };

  const handleSelectedFilterChange = (value) => {
    setSelectedFilter(value);
    setPage(1);
  };

  const handleOdooSyncFilterChange = (value) => {
    setOdooSyncFilter(value);
    setPage(1);
  };

  const handleProductClick = (productId) => {
    navigate(`/products/${productId}`);
  };

  return (
    <div
      className="p-6 space-y-4"
      data-testid="products-page"
    >
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">
            Products
          </h1>

          <p className="text-zinc-500 text-sm mt-1">
            {total.toLocaleString()} products in catalog
          </p>
        </div>
      </div>

      <div
        className="flex flex-wrap gap-3 items-end"
        data-testid="product-filters"
      >
        <form
          onSubmit={handleSearch}
          className="flex gap-2"
        >
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />

            <Input
              placeholder="Search products..."
              value={search}
              onChange={(event) =>
                setSearch(event.target.value)
              }
              className="pl-10 w-64 bg-zinc-950 border-zinc-800 rounded-none text-sm font-mono placeholder:text-zinc-600 focus:border-blue-500"
              data-testid="search-input"
            />
          </div>
        </form>

        <Select
          value={supplier}
          onValueChange={handleSupplierChange}
        >
          <SelectTrigger
            className="w-44 bg-zinc-950 border-zinc-800 rounded-none text-sm"
            data-testid="filter-supplier"
          >
            <SelectValue placeholder="Supplier" />
          </SelectTrigger>

          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">
              All Suppliers
            </SelectItem>

            {suppliers.map((supplierItem) => (
              <SelectItem
                key={supplierItem.id}
                value={supplierItem.id}
              >
                {supplierItem.supplier_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={category}
          onValueChange={handleCategoryChange}
        >
          <SelectTrigger
            className="w-40 bg-zinc-950 border-zinc-800 rounded-none text-sm"
            data-testid="filter-category"
          >
            <SelectValue placeholder="Category" />
          </SelectTrigger>

          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">
              All Categories
            </SelectItem>

            {categories.map((categoryItem) => (
              <SelectItem
                key={categoryItem}
                value={categoryItem}
              >
                {categoryItem}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={brand}
          onValueChange={handleBrandChange}
        >
          <SelectTrigger
            className="w-40 bg-zinc-950 border-zinc-800 rounded-none text-sm"
            data-testid="filter-brand"
          >
            <SelectValue placeholder="Brand" />
          </SelectTrigger>

          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">
              All Brands
            </SelectItem>

            {brands.map((brandItem) => (
              <SelectItem
                key={brandItem}
                value={brandItem}
              >
                {brandItem}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={selectedFilter}
          onValueChange={handleSelectedFilterChange}
        >
          <SelectTrigger
            className="w-44 bg-zinc-950 border-zinc-800 rounded-none text-sm"
            data-testid="filter-selection"
          >
            <SelectValue placeholder="Selection" />
          </SelectTrigger>

          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">
              All Products
            </SelectItem>

            <SelectItem value="selected">
              Selected for Odoo
            </SelectItem>

            <SelectItem value="not_selected">
              Not Selected
            </SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={odooSyncFilter}
          onValueChange={handleOdooSyncFilterChange}
        >
          <SelectTrigger
            className="w-44 bg-zinc-950 border-zinc-800 rounded-none text-sm"
            data-testid="filter-odoo-sync"
          >
            <SelectValue placeholder="Odoo Sync Status" />
          </SelectTrigger>

          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">
              All Sync Status
            </SelectItem>

            <SelectItem value="synced">
              Synced to Odoo
            </SelectItem>

            <SelectItem value="not_synced">
              Not Synced
            </SelectItem>
          </SelectContent>
        </Select>

        <div className="flex border border-zinc-800 ml-auto">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setViewMode("grid")}
            className={`rounded-none px-3 ${
              viewMode === "grid"
                ? "bg-zinc-800 text-white"
                : "text-zinc-500 hover:text-white"
            }`}
            data-testid="view-grid"
          >
            <Grid3X3 className="w-4 h-4" />
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setViewMode("list")}
            className={`rounded-none px-3 ${
              viewMode === "list"
                ? "bg-zinc-800 text-white"
                : "text-zinc-500 hover:text-white"
            }`}
            data-testid="view-list"
          >
            <List className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {viewMode === "list" && (
        <div className="flex items-center justify-between p-3 bg-zinc-900/50 border border-zinc-800">
          <div className="flex items-center gap-4">
            <Checkbox
              checked={
                products.length > 0 &&
                selectedProducts.size === products.length
              }
              onCheckedChange={selectAllProducts}
              data-testid="select-all-checkbox"
            />

            <span className="text-sm text-zinc-400">
              {selectedProducts.size > 0
                ? `${selectedProducts.size} selected`
                : "Select all"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {selectedProducts.size > 0 && (
              <Button
                variant="destructive"
                size="sm"
                onClick={deleteSelectedProducts}
                disabled={deleting}
                className="rounded-none bg-red-900/50 hover:bg-red-900 border-red-800"
                data-testid="delete-selected-btn"
              >
                {deleting ? (
                  <Loader2 className="w-4 h-4 animate-spin mr-1" />
                ) : (
                  <Trash2 className="w-4 h-4 mr-1" />
                )}

                Delete Selected
              </Button>
            )}

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-none border-zinc-700 text-zinc-300"
                >
                  <MoreVertical className="w-4 h-4" />
                </Button>
              </DropdownMenuTrigger>

              <DropdownMenuContent
                align="end"
                className="bg-zinc-900 border-zinc-800"
              >
                <DropdownMenuItem
                  onClick={deleteAllProducts}
                  className="text-red-400 focus:text-red-300 focus:bg-red-950/30"
                  disabled={deleting}
                >
                  <Trash2 className="w-4 h-4 mr-2" />
                  Delete All Products
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      )}

      {loading ? (
        <div
          className={
            viewMode === "grid"
              ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3"
              : "space-y-2"
          }
        >
          {Array(8)
            .fill(0)
            .map((_, index) => (
              <div
                key={index}
                className={
                  viewMode === "grid"
                    ? "h-48 bg-zinc-800/30 animate-pulse rounded-sm"
                    : "h-16 bg-zinc-800/30 animate-pulse rounded-sm"
                }
              />
            ))}
        </div>
      ) : products.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
          <Package
            className="w-12 h-12 mb-4 text-zinc-700"
            strokeWidth={1}
          />

          <p className="font-mono text-sm">
            NO PRODUCTS FOUND
          </p>

          <p className="text-xs mt-1">
            Sync products from a supplier or seed demo data
          </p>
        </div>
      ) : viewMode === "grid" ? (
        <div
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3"
          data-testid="product-grid"
        >
          {products.map((product) => {
            const imageUrl = getProductImage(product);

            return (
              <Card
                key={product.id}
                className="bg-zinc-900/50 border-zinc-800 rounded-sm hover:border-zinc-700 transition-colors group overflow-hidden"
                data-testid={`product-card-${product.id}`}
              >
                <CardContent className="p-0">
                  <div
                    className="relative h-32 bg-zinc-800/50 flex items-center justify-center border-b border-zinc-800/50 overflow-hidden cursor-pointer"
                    onClick={() =>
                      handleProductClick(product.id)
                    }
                  >
                    {imageUrl ? (
                      <ProductImage
                        product={product}
                        className="relative z-10 h-full w-full object-contain p-2"
                        fallbackIconSize="w-8 h-8"
                      />
                    ) : (
                      <div className="absolute inset-0 flex items-center justify-center bg-zinc-800/50">
                        <Package
                          className="w-8 h-8 text-zinc-700"
                          strokeWidth={1}
                        />
                      </div>
                    )}
                  </div>

                  <div className="p-3 space-y-2">
                    <div className="flex items-start justify-between">
                      <div
                        className="cursor-pointer flex-1 min-w-0"
                        onClick={() =>
                          handleProductClick(product.id)
                        }
                      >
                        <p className="text-sm font-medium text-zinc-200 group-hover:text-white transition-colors line-clamp-1">
                          {product.product_name}
                        </p>

                        <p className="text-xs font-mono text-zinc-500 mt-0.5">
                          {product.supplier_sku}
                        </p>
                      </div>

                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0 text-zinc-500 hover:text-white"
                          >
                            <MoreVertical className="w-4 h-4" />
                          </Button>
                        </DropdownMenuTrigger>

                        <DropdownMenuContent
                          align="end"
                          className="bg-zinc-900 border-zinc-800"
                        >
                          <DropdownMenuItem
                            onClick={() =>
                              syncProduct(
                                product.id,
                                "pricing"
                              )
                            }
                            disabled={
                              syncing[
                                `${product.id}-pricing`
                              ]
                            }
                            className="text-zinc-300 focus:bg-zinc-800"
                          >
                            {syncing[
                              `${product.id}-pricing`
                            ] ? (
                              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            ) : (
                              <DollarSign className="w-4 h-4 mr-2" />
                            )}
                            Sync Pricing
                          </DropdownMenuItem>

                          <DropdownMenuItem
                            onClick={() =>
                              syncProduct(
                                product.id,
                                "inventory"
                              )
                            }
                            disabled={
                              syncing[
                                `${product.id}-inventory`
                              ]
                            }
                            className="text-zinc-300 focus:bg-zinc-800"
                          >
                            {syncing[
                              `${product.id}-inventory`
                            ] ? (
                              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            ) : (
                              <Warehouse className="w-4 h-4 mr-2" />
                            )}
                            Sync Inventory
                          </DropdownMenuItem>

                          <DropdownMenuItem
                            onClick={() =>
                              syncProduct(
                                product.id,
                                "media"
                              )
                            }
                            disabled={
                              syncing[
                                `${product.id}-media`
                              ]
                            }
                            className="text-zinc-300 focus:bg-zinc-800"
                          >
                            {syncing[
                              `${product.id}-media`
                            ] ? (
                              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            ) : (
                              <ImageIcon className="w-4 h-4 mr-2" />
                            )}
                            Sync Media
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>

                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-400">
                        {product.brand}
                      </span>

                      <span className="font-mono text-zinc-300 tabular-nums">
                        $
                        {Number(
                          product.base_price || 0
                        ).toFixed(2)}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-500">
                        {product.variant_count || 0} variants
                      </span>

                      <span
                        className={`px-1.5 py-0.5 font-mono border rounded-none ${
                          product.status === "active"
                            ? "bg-emerald-950/50 text-emerald-400 border-emerald-800"
                            : "bg-zinc-800 text-zinc-500 border-zinc-700"
                        }`}
                      >
                        {product.status}
                      </span>
                    </div>

                    <div className="flex items-center justify-between pt-1 border-t border-zinc-800/50">
                      <span className="text-xs text-zinc-400">
                        Odoo
                      </span>

                      <Switch
                        checked={
                          !!product.selected_for_odoo
                        }
                        onCheckedChange={() =>
                          toggleSelection(
                            product.id,
                            product.selected_for_odoo
                          )
                        }
                        data-testid={`odoo-toggle-${product.id}`}
                        className="data-[state=checked]:bg-blue-600"
                      />
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="text-xs text-zinc-400">
                        Lightspeed
                      </span>

                      <Switch
                        checked={
                          !!product.selected_for_lightspeed
                        }
                        onCheckedChange={() =>
                          toggleLightspeedSelection(
                            product.id,
                            product.selected_for_lightspeed
                          )
                        }
                        data-testid={`ls-toggle-${product.id}`}
                        className="data-[state=checked]:bg-emerald-600"
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : (
        <div
          className="space-y-2"
          data-testid="product-list"
        >
          {products.map((product) => (
            <div
              key={product.id}
              className={`flex items-center gap-4 p-3 bg-zinc-900/50 border transition-colors ${
                selectedProducts.has(product.id)
                  ? "border-blue-600 bg-blue-950/20"
                  : "border-zinc-800 hover:border-zinc-700"
              }`}
              data-testid={`product-row-${product.id}`}
            >
              <Checkbox
                checked={selectedProducts.has(product.id)}
                onCheckedChange={() =>
                  toggleProductSelect(product.id)
                }
                data-testid={`select-product-${product.id}`}
              />

              <div
                className="relative w-16 h-16 bg-zinc-800/50 flex items-center justify-center overflow-hidden cursor-pointer shrink-0"
                onClick={() =>
                  handleProductClick(product.id)
                }
              >
                <ProductImage
                  product={product}
                  className="relative z-10 h-full w-full object-contain p-1"
                  fallbackIconSize="w-6 h-6"
                />
              </div>

              <div
                className="flex-1 min-w-0 cursor-pointer"
                onClick={() =>
                  handleProductClick(product.id)
                }
              >
                <p className="text-sm font-medium text-zinc-200 truncate">
                  {product.product_name}
                </p>

                <p className="text-xs font-mono text-zinc-500">
                  {product.supplier_sku}
                </p>
              </div>

              <div className="text-right shrink-0">
                <p className="text-xs text-zinc-400">
                  {product.brand}
                </p>

                <p className="text-sm font-mono text-zinc-300">
                  $
                  {Number(
                    product.base_price || 0
                  ).toFixed(2)}
                </p>
              </div>

              <div className="text-center shrink-0 w-20">
                <p className="text-xs text-zinc-500">
                  {product.variant_count || 0} variants
                </p>

                <span
                  className={`inline-block px-1.5 py-0.5 text-xs font-mono border rounded-none ${
                    product.status === "active"
                      ? "bg-emerald-950/50 text-emerald-400 border-emerald-800"
                      : "bg-zinc-800 text-zinc-500 border-zinc-700"
                  }`}
                >
                  {product.status}
                </span>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    syncProduct(
                      product.id,
                      "pricing"
                    )
                  }
                  disabled={
                    syncing[
                      `${product.id}-pricing`
                    ]
                  }
                  className="h-8 px-2 text-zinc-500 hover:text-emerald-400"
                  title="Sync Pricing"
                >
                  {syncing[
                    `${product.id}-pricing`
                  ] ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <DollarSign className="w-4 h-4" />
                  )}
                </Button>

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    syncProduct(
                      product.id,
                      "inventory"
                    )
                  }
                  disabled={
                    syncing[
                      `${product.id}-inventory`
                    ]
                  }
                  className="h-8 px-2 text-zinc-500 hover:text-blue-400"
                  title="Sync Inventory"
                >
                  {syncing[
                    `${product.id}-inventory`
                  ] ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Warehouse className="w-4 h-4" />
                  )}
                </Button>

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    syncProduct(
                      product.id,
                      "media"
                    )
                  }
                  disabled={
                    syncing[
                      `${product.id}-media`
                    ]
                  }
                  className="h-8 px-2 text-zinc-500 hover:text-purple-400"
                  title="Sync Media"
                >
                  {syncing[
                    `${product.id}-media`
                  ] ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <ImageIcon className="w-4 h-4" />
                  )}
                </Button>
              </div>

              <div className="flex items-center gap-2 shrink-0 border-l border-zinc-800 pl-3">
                <span className="text-xs text-zinc-500">
                  Odoo
                </span>

                <Switch
                  checked={
                    !!product.selected_for_odoo
                  }
                  onCheckedChange={() =>
                    toggleSelection(
                      product.id,
                      product.selected_for_odoo
                    )
                  }
                  data-testid={`odoo-toggle-list-${product.id}`}
                  className="data-[state=checked]:bg-blue-600"
                />
              </div>

              <div className="flex items-center gap-2 shrink-0 border-l border-zinc-800 pl-3">
                <span className="text-xs text-zinc-500">
                  LS
                </span>

                <Switch
                  checked={
                    !!product.selected_for_lightspeed
                  }
                  onCheckedChange={() =>
                    toggleLightspeedSelection(
                      product.id,
                      product.selected_for_lightspeed
                    )
                  }
                  data-testid={`ls-toggle-list-${product.id}`}
                  className="data-[state=checked]:bg-emerald-600"
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {pages > 1 && (
        <div
          className="flex items-center justify-between pt-4"
          data-testid="pagination"
        >
          <span className="text-xs text-zinc-500 font-mono">
            Page {page} of {pages} ({total} total)
          </span>

          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setPage((currentPage) =>
                  Math.max(1, currentPage - 1)
                )
              }
              disabled={page === 1}
              className="rounded-none border-zinc-700 text-zinc-300 hover:bg-zinc-800"
              data-testid="prev-page-btn"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setPage((currentPage) =>
                  Math.min(
                    pages,
                    currentPage + 1
                  )
                )
              }
              disabled={page === pages}
              className="rounded-none border-zinc-700 text-zinc-300 hover:bg-zinc-800"
              data-testid="next-page-btn"
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}