export const advancedDefaults = {
  images: "",
  pricing: "",
  stock: "",
  colour: "",
  size: "",
  price_min: "",
  price_max: "",
  variants_min: "",
  variants_max: "",
  updated_from: "",
  updated_to: "",
};
export function readCatalogueFilters(search) {
  const p = new URLSearchParams(search);
  return {
    supplier: p.get("supplier_id") || "",
    category: (p.get("category")||"").trim().toLowerCase()==="uncategorized"?"__uncategorized__":p.get("category")||"",
    brand: p.get("brand") || "",
    search: p.get("search") || "",
    sort: p.get("sort") || "newest",
    advanced: Object.fromEntries(
      Object.keys(advancedDefaults).map((key) => [key, p.get(key) || ""]),
    ),
  };
}
export function advancedError(values) {
  for (const [a, b, label] of [
    ["price_min", "price_max", "Price"],
    ["variants_min", "variants_max", "Variant"],
  ]) {
    for (const key of [a, b])
      if (
        values[key] !== "" &&
        (!Number.isFinite(Number(values[key])) ||
          Number(values[key]) < 0 ||
          (key.startsWith("variants") &&
            !Number.isInteger(Number(values[key]))))
      )
        return `${label} ranges need non-negative ${label === "Variant" ? "whole numbers" : "numbers"}.`;
    if (
      values[a] !== "" &&
      values[b] !== "" &&
      Number(values[a]) > Number(values[b])
    )
      return `${label} minimum cannot exceed maximum.`;
  }
  if (
    values.updated_from &&
    values.updated_to &&
    values.updated_from > values.updated_to
  )
    return "The start date cannot follow the end date.";
  return "";
}
export function catalogueParams({
  page = 1,
  search = "",
  supplier = "",
  category = "",
  brand = "",
  sort = "newest",
  advanced = {},
}) {
  return {
    page,
    limit: 24,
    ...(search.trim() ? { search: search.trim() } : {}),
    ...(supplier ? { supplier_id: supplier } : {}),
    ...(category ? { category } : {}),
    ...(brand ? { brand } : {}),
    sort,
    ...Object.fromEntries(
      Object.entries(advanced).filter(
        ([, value]) => value !== "" && value != null,
      ),
    ),
  };
}
