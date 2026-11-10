"""Explicit, parameterized catalogue filters. No default visibility exclusions."""
from datetime import date
import math

UNCATEGORIZED='__uncategorized__'
UNBRANDED='__unbranded__'
UNASSIGNED='__unassigned__'
IMAGE_EXISTS="EXISTS (SELECT 1 FROM product_media pm WHERE pm.product_id=p.id AND pm.media_type='image' AND (COALESCE(pm.url,'')<>'' OR COALESCE(pm.image_base64,'')<>''))"
VARIANT_COUNT='(SELECT COUNT(*) FROM product_variants v WHERE v.product_id=p.id)'
COLOUR="LOWER(BTRIM(REPLACE(REPLACE(RTRIM(LTRIM(COALESCE(v.color,''), chr(39)||'’‘`~ '),'.'),' / ','/'),' /','/')))"
SAVED_INVENTORY='(SELECT CASE WHEN COUNT(*)=0 OR COUNT(*) FILTER(WHERE v.inventory IS NULL OR v.inventory<0)>0 THEN NULL ELSE SUM(v.inventory) END FROM product_variants v WHERE v.product_id=p.id)'
BRAND_SORT="CASE WHEN LOWER(BTRIM(p.brand))='unbranded' THEN NULL ELSE LOWER(NULLIF(BTRIM(p.brand),'')) END"
SORTS={'newest':'p.created_at DESC, p.id','oldest':'p.created_at ASC, p.id',
       'name_asc':"LOWER(COALESCE(p.product_name,'')) ASC, p.id",'name_desc':"LOWER(COALESCE(p.product_name,'')) DESC, p.id",
       'price_asc':'p.base_price ASC NULLS LAST, p.id','price_desc':'p.base_price DESC NULLS LAST, p.id',
       'variants_desc':VARIANT_COUNT+' DESC, p.id','variants_asc':VARIANT_COUNT+' ASC, p.id',
       'brand_asc':BRAND_SORT+' ASC NULLS LAST, p.id','brand_desc':BRAND_SORT+' DESC NULLS LAST, p.id',
       'inventory_asc':SAVED_INVENTORY+' ASC NULLS LAST, p.id','inventory_desc':SAVED_INVENTORY+' DESC NULLS LAST, p.id',
       'updated_asc':'p.updated_at ASC NULLS LAST, p.id','updated':'p.updated_at DESC NULLS LAST, p.id'}


def catalog_filter(values):
    clauses=[];args=[]
    def bind(value):args.append(value);return '$'+str(len(args))
    supplier=values.get('supplier_id')
    if supplier and supplier!='all':
        if supplier==UNASSIGNED:clauses.append('NOT EXISTS (SELECT 1 FROM suppliers s WHERE s.id=p.supplier_id)')
        else:clauses.append('p.supplier_id='+bind(supplier))
    for field,marker,label in [('category',UNCATEGORIZED,'uncategorized'),('brand',UNBRANDED,'unbranded')]:
        value=values.get(field)
        if value and value!='all':
            if value==marker or str(value).strip().casefold()==label:
                clauses.append(f"(NULLIF(BTRIM(p.{field}),'') IS NULL OR LOWER(BTRIM(p.{field}))='{label}')")
            else:clauses.append(f'BTRIM(p.{field})='+bind(value.strip()))
    if values.get('search'):
        token=bind('%'+values['search'].strip()+'%')
        clauses.append(f'(p.product_name ILIKE {token} OR p.supplier_sku ILIKE {token})')
    for key,column,operator in [('price_min','p.base_price','>='),('price_max','p.base_price','<='),('variants_min',VARIANT_COUNT,'>='),('variants_max',VARIANT_COUNT,'<=')]:
        value=values.get(key)
        if value is not None and value!='':
            try:number=float(value)
            except (ValueError,TypeError):raise ValueError('Enter valid price and variant ranges') from None
            if not math.isfinite(number) or number<0 or (key.startswith('variants') and not number.is_integer()):raise ValueError('Ranges must use non-negative values; variant counts must be whole numbers')
            clauses.append(column+operator+bind(int(number) if key.startswith('variants') else number))
    for first,last in [('price_min','price_max'),('variants_min','variants_max')]:
        if values.get(first) not in (None,'') and values.get(last) not in (None,'') and float(values[first])>float(values[last]):raise ValueError('Minimum values cannot exceed maximum values')
    image=values.get('images') or ''
    if image not in ('','with','without'):raise ValueError('Unknown image filter')
    if image:clauses.append(('NOT ' if image=='without' else '')+IMAGE_EXISTS)
    pricing=values.get('pricing') or ''
    if pricing not in ('','priced','missing'):raise ValueError('Unknown pricing filter')
    if pricing:clauses.append('p.base_price>0' if pricing=='priced' else '(p.base_price IS NULL OR p.base_price<=0)')
    stock=values.get('stock') or ''
    if stock not in ('','in_stock','out_of_stock','unknown'):raise ValueError('Unknown inventory filter')
    positive='EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id AND v.inventory>0)'
    unknown='EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id AND (v.inventory IS NULL OR v.inventory<0))'
    exists='EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id)'
    if stock=='in_stock':clauses.append(positive)
    elif stock=='out_of_stock':clauses.append(f'({exists} AND NOT {positive} AND NOT {unknown})')
    elif stock=='unknown':clauses.append(f'(NOT {positive} AND (NOT {exists} OR {unknown}))')
    if values.get('colour'):clauses.append(f'EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id AND {COLOUR}={bind(values["colour"].strip().casefold())})')
    if values.get('size'):clauses.append('EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id AND LOWER(BTRIM(v.size))='+bind(values['size'].strip().casefold())+')')
    dates={}
    for key,operator in [('updated_from','>='),('updated_to','<')]:
        value=values.get(key)
        if value:
            try:parsed=date.fromisoformat(str(value))
            except ValueError:raise ValueError('Use YYYY-MM-DD for updated dates') from None
            dates[key]=parsed;token=bind(parsed)
            clauses.append(f'p.updated_at {operator} ({token}::date'+("+1" if key=='updated_to' else '')+')')
    if len(dates)==2 and dates['updated_from']>dates['updated_to']:raise ValueError('The start date cannot follow the end date')
    if values.get('selected') is not None:clauses.append('p.selected_for_odoo='+bind(values['selected']))
    if values.get('odoo_status') and values['odoo_status']!='all':clauses.append('p.odoo_sync_status='+bind(values['odoo_status']))
    order=values.get('sort') or 'newest'
    if order not in SORTS:raise ValueError('Unknown catalogue sort order')
    return ' AND '.join(clauses) or '1=1',args,SORTS[order]
