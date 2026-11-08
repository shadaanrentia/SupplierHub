// Suggestions use full paths and require a unique category in the current cache.
// They are never saved until the user clicks the suggestion.
const known = {
  "100% BASIC TEES": "T-Shirts",
  "50/50 BASIC TEES": "T-Shirts",
  "LADIES TEES": "T-Shirts",
  "YOUTH 100% BASIC TEE": "T-Shirts",
  "FASHION TEES": "T-Shirts",
  "LONG SLEEVE TEES": "T-Shirts",
  "100% SPORTSHIRTS": "Polos & Knits",
  "50/50 SPORTSHIRTS": "Polos & Knits",
  "LADIES SPORTSHIRTS": "Polos & Knits",
  "LADIES WOVENS": "Woven Shirts",
  WOVENS: "Woven Shirts",
  "WOVEN SHIRTS": "Woven Shirts",
  "BASIC FLEECE": "Sweatshirts & Fleece",
  FLEECE: "Sweatshirts & Fleece",
  "PREMIUM FLEECE": "Sweatshirts & Fleece",
  "YOUTH FLEECE": "Sweatshirts & Fleece",
};
const paths = {
  Aprons: "Accessories",
  Bags: "Accessories",
  Blankets: "Accessories",
  Towels: "Accessories",
  "Activewear Bottoms": "Bottoms",
  Coveralls: "Bottoms",
  Loungewear: "Bottoms",
  Pants: "Bottoms",
  Shorts: "Bottoms",
  "Sweatpants & Joggers": "Bottoms",
  Infants: "Gender",
  "Mens & Unisex": "Gender",
  Toddlers: "Gender",
  Womens: "Gender",
  Youth: "Gender",
  Beanies: "Headwear",
  "Bucket Hats": "Headwear",
  Hats: "Headwear",
  Visors: "Headwear",
  Jackets: "Outerwear",
  Vests: "Outerwear",
  "Activewear Tops": "Tops",
  "Polos & Knits": "Tops",
  "Sweatshirts & Fleece": "Tops",
  "T-Shirts": "Tops",
  "Woven Shirts": "Tops",
};
const clean = (value) =>
  String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
export function categorySuggestion(source, options) {
  const key = String(source || "")
    .replace(/\s+/g, " ")
    .trim()
    .toUpperCase();
  const leaf =
    known[key] || Object.keys(paths).find((name) => name.toUpperCase() === key);
  if (!leaf) return null;
  const expected = clean(`Apparel > ${paths[leaf]} > ${leaf}`);
  const matches = options.filter((option) => clean(option.label) === expected);
  return matches.length === 1 ? matches[0] : null;
}
