"""Import adapters; source metadata retained, no Lightspeed writes."""
import json,math,threading
from urllib.parse import urlparse
import requests

def number(value,positive=False):
    try:
        if isinstance(value,bool):return None
        value=float(value)
        return value if math.isfinite(value) and (value>0 if positive else value>=0) else None
    except (ValueError,TypeError):return None

def options(rows):
    result={}
    for text in rows or []:
        if isinstance(text,str) and ':' in text:
            k,v=text.split(':',1);result[k.strip().lower()]=v.strip()
    return result

def media(row,parts=None):
    urls=[row.get('base_image'),*(row.get('additional_images') or [])]
    seen=set();result=[]
    for url in urls:
        if isinstance(url,str) and url.startswith(('https://','http://')) and url not in seen:
            seen.add(url);result.append(dict(url=url,type='image',is_primary=not result,source_part_ids=parts or []))
    return result

class SupplierFailure(Exception):
    def __init__(self,code,message):
        super().__init__(message);self.code=code

class Adapter:
    import_only=True
    def __init__(self,supplier):
        self.supplier=supplier;self.services={};self.discovery_limit=1500;self.lock=threading.RLock();self.cache={}
    def result(self,fn):
        try:return dict(success=True,import_only=True,**fn())
        except SupplierFailure as e:return dict(success=False,error_code=e.code,error=str(e))
        except requests.Timeout:return dict(success=False,error_code='TIMEOUT',error='Supplier request timed out')
        except requests.ConnectionError:return dict(success=False,error_code='CONNECTION_RESET',error='Supplier connection failed')
        except requests.HTTPError as e:return dict(success=False,error_code='ACCESS_DENIED' if e.response is not None and e.response.status_code in (401,403) else 'UNAVAILABLE',error='Supplier HTTP request failed')
        except Exception as e:
            code='ACCESS_DENIED' if any(t in str(e) for t in ('HTTP 403','HTTP=403','HTTP 401','Cloudflare')) else 'INVALID_RESPONSE'
            return dict(success=False,error_code=code,error=str(e)[:300])
    def test_connection(self):
        limit=self.discovery_limit
        try:
            self.discovery_limit=1;r=self.get_sellable_products()
            return dict(success=r.get('success',False),connected=r.get('success',False),message='Catalogue request successful' if r.get('success') else r.get('error','Request failed'))
        finally:self.discovery_limit=limit

class Caldwell(Adapter):
    def __init__(self,supplier):
        super().__init__(supplier);self.base=(supplier.get('api_base_url') or 'https://caldwellrecognition.com').rstrip('/')
        parsed=urlparse(self.base)
        if parsed.scheme!='https' or parsed.hostname not in ('caldwellrecognition.com','www.caldwellrecognition.com'):raise ValueError('Use https://caldwellrecognition.com for Caldwell')
        self.token=None
        self.headers={'Accept':'application/json','Content-Type':'application/json',
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36',
            'Accept-Language':'en-US,en;q=0.9'}
    @staticmethod
    def checked(response,stage):
        status=response.status_code
        if status>=400:
            code='ACCESS_DENIED' if status in (401,403) else 'RATE_LIMIT' if status==429 else 'UNAVAILABLE' if status>=500 else 'ENDPOINT' if status==404 else 'SUPPLIER_ERROR'
            hint='Check the customer login email/password.' if status==401 and stage=='login' else 'Catalogue authorization was rejected.' if status==401 else 'Access was forbidden; check account permission or network/security filtering.' if status==403 else 'The supplier rejected the request.'
            raise SupplierFailure(code,f'Caldwell {stage} returned HTTP {status}. {hint}')
    def fetch(self,params):
        with self.lock:
            for attempt in range(2):
                if not self.token:
                    r=requests.post(self.base+'/rest/V1/integration/customer/token',json={'username':self.supplier.get('account_number'),'password':self.supplier.get('password')},headers=self.headers,timeout=(10,30));self.checked(r,'login');self.token=r.json()
                    if not isinstance(self.token,str) or not self.token:raise ValueError('Invalid Caldwell token response')
                r=requests.get(self.base+'/rest/V1/caldwell/inventory',params=params,headers={**self.headers,'Authorization':'Bearer '+self.token},timeout=(10,60))
                if r.status_code==401 and attempt==0:self.token=None;continue
                self.checked(r,'inventory catalogue');data=r.json()
                if not isinstance(data,dict) or not isinstance(data.get('items'),list):raise ValueError('Invalid Caldwell inventory envelope')
                return data
            raise ValueError('Caldwell authentication failed')
    def get_sellable_products(self):
        def work():
            seen=set();page=1;total=None
            while len(seen)<self.discovery_limit:
                data=self.fetch({'page':page,'pageSize':min(200,self.discovery_limit)})
                total=int(data.get('total_count',0));items=data['items']
                if not items and len(seen)<total:raise ValueError('Caldwell returned an empty page before total_count')
                added=0
                for row in items:
                    sku=str(row.get('sku') or '').strip()
                    if sku and sku not in seen:seen.add(sku);added+=1;self.cache[sku]=row
                if len(seen)>=total:break
                if not added:raise ValueError('Caldwell pagination repeated without new SKUs')
                page+=1
            return {'products':[{'product_id':s} for s in self.cache][:self.discovery_limit]}
        return self.result(work)
    def row(self,sku):
        with self.lock:
            if sku not in self.cache:
                rows=self.fetch({'sku':sku})['items'];exact=[r for r in rows if str(r.get('sku') or '').strip()==sku]
                if len(exact)!=1:raise ValueError('Caldwell did not return exactly one matching SKU')
                self.cache[sku]=exact[0]
            return self.cache[sku]
    def get_product(self,sku):
        def work():
            r=self.row(sku);variants=[];images=media(r)
            for v in r.get('variants') or []:
                opt=options(v.get('options'));vs=str(v.get('sku') or '').strip()
                if not vs:raise ValueError('Caldwell child is missing SKU')
                variant={'variant_sku':vs,'color':opt.get('color') or opt.get('colour') or '', 'size':opt.get('size') or ''}
                cost=number(v.get('final_price'),True);qty=number(v.get('qty'))
                if cost is not None:variant['price']=cost
                if qty is not None and qty.is_integer():variant['inventory']=int(qty)
                variants.append(variant);images.extend(media(v,[vs]))
            product=dict(product_name=r.get('name') or sku,description=r.get('description') or r.get('short_description') or '',category=next(iter(r.get('categories') or []),''),variants=variants,_source_metadata=r,_source_product_type=r.get('product_type') or 'simple',_import_media=images)
            costs=[number(v.get('price'),True) for v in variants];cost=number(r.get('final_price'),True) if not variants else min((c for c in costs if c is not None),default=None)
            if cost is not None:product['price']=cost
            return {'product':product}
        return self.result(work)
    def get_pricing(self,sku):
        def work():
            r=self.row(sku);rows=r.get('variants') or [r]
            return {'pricing':[{'part_id':v.get('sku'),'prices':[{'min_quantity':1,'price':v.get('final_price')}]} for v in rows],**({'standard_price':r.get('final_price')} if not r.get('variants') else {})}
        return self.result(work)
    def get_inventory(self,sku):
        return self.result(lambda:{'inventory':[dict(part_id=v.get('sku'),quantity_available=v.get('qty'),warehouses=[]) for v in self.row(sku).get('variants') or [self.row(sku)]],**({'standard_inventory':self.row(sku).get('qty')} if not self.row(sku).get('variants') else {})})
    def get_media(self,sku):
        r=self.get_product(sku)
        return dict(success=True,import_only=True,media=r['product']['_import_media']) if r.get('success') else r

class Athletic(Adapter):
    def __init__(self,supplier):
        super().__init__(supplier)
        from .ak_client import AthleticKnitClient
        self.client=AthleticKnitClient(supplier)
    def parsed(self,sku):
        from .product_parser import parse_product
        with self.lock:
            if sku not in self.cache:self.cache[sku]=parse_product(self.client.get_product_raw(sku))
            r=self.cache[sku]
            if not r.get('name'):raise ValueError('Athletic Knit returned no product name')
            return r
    def get_sellable_products(self):
        def work():
            from .sellable_parser import parse_sellable_products
            data=parse_sellable_products(self.client.get_sellable_products_raw())
            return {'products':[{'product_id':s} for s in data.get('product_ids',[])][:self.discovery_limit]}
        return self.result(work)
    def get_product(self,sku):
        def work():
            r=self.parsed(sku);variants=[]
            for v in r.get('variants',[]):
                x=dict(variant_sku=v['part_id'],color=v.get('color') or '',size=v.get('size') or '')
                tiers=sorted(v.get('prices') or [],key=lambda p:p.get('quantity_min') or 1)
                price=number(tiers[0].get('price'),True) if tiers else None
                if price is not None:x['price']=price
                variants.append(x)
            product=dict(product_name=r['name'],description=r.get('description') or '',brand=r.get('brand') or '',category=r.get('category') or '',variants=variants,_source_metadata=r,_source_product_type='configurable' if variants else 'simple')
            costs=[v['price'] for v in variants if v.get('price')]
            if costs:product['price']=min(costs)
            return {'product':product}
        return self.result(work)
    def get_pricing(self,sku):
        return self.result(lambda:{'pricing':[{'part_id':v['part_id'],'prices':[dict(min_quantity=p.get('quantity_min') or 1,price=p.get('price')) for p in v.get('prices') or []]} for v in self.parsed(sku).get('variants',[])]})
    def get_inventory(self,sku):
        def work():
            from .inventory_parser import parse_inventory
            r=parse_inventory(self.client.get_inventory_raw(sku))
            return {'inventory':r.get('items',[])}
        return self.result(work)
    def get_media(self,sku):
        def work():
            from .media_parser import parse_media
            r=parse_media(self.client.get_media_raw(sku))
            return {'media':[dict(v,type=v.get('media_type') or 'image',source_part_ids=v.get('part_ids') or []) for v in r.get('unique_media',[])]}
        return self.result(work)

def make_connector(supplier):
    style=supplier.get('endpoint_style') or ''
    if style=='athletic_knit':return Athletic(supplier)
    if style=='caldwell':return Caldwell(supplier)
    from promostandards import PromoStandardsConnector
    return PromoStandardsConnector(supplier)
