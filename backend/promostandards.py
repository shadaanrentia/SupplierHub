"""
PromoStandards SOAP Connector - Raw XML approach.
Raw SOAP reads with ATC-specific request fields from the supplied integration guide.
Uses standardized XML namespaces and operation names.
"""
import logging
import time
import contextvars
import json
import math
from urllib.parse import urlsplit
import requests
from lxml import etree
from typing import Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger(__name__)

# Standard PromoStandards XML Namespaces
NS = {
    'soap': 'http://schemas.xmlsoap.org/soap/envelope/',
    'pd': 'http://www.promostandards.org/WSDL/ProductDataService/2.0.0/',
    'pd_so': 'http://www.promostandards.org/WSDL/ProductDataService/2.0.0/SharedObjects/',
    'inv': 'http://www.promostandards.org/WSDL/Inventory/2.0.0/',
    'inv_so': 'http://www.promostandards.org/WSDL/Inventory/2.0.0/SharedObjects/',
    'ppc': 'http://www.promostandards.org/WSDL/PricingAndConfiguration/1.0.0/',
    'ppc_so': 'http://www.promostandards.org/WSDL/PricingAndConfiguration/1.0.0/SharedObjects/',
    'mc': 'http://www.promostandards.org/WSDL/MediaService/1.0.0/',
    'mc_so': 'http://www.promostandards.org/WSDL/MediaService/1.0.0/SharedObjects/',
    'bd': 'https://edi.atc-apparel.com/bulk-data/',
}

# Known supplier endpoint patterns (service endpoints, NOT WSDLs)
SUPPLIER_PATTERNS = {
    "ss": {
        "label": "S&S Activewear",
        "product_data": "{base}/ProductData/v2/ProductDataServicev2.svc",
        "inventory": "{base}/Inventory/v2/InventoryService.svc",
        "pricing": "{base}/PricingAndConfiguration/v1/PricingAndConfigurationService.svc",
        "media": "{base}/MediaContent/v1/MediaContentService.svc",
        "bulk_data": "{base}/BulkData/v1/BulkDataService.svc",
    },
    "atc": {
        "label": "ATC / SanMar",
        "product_data": "{base}/pstd/productdata2.0/ProductDataServiceV2.php",
        "inventory": "{base}/pstd/inventory2.0/InventoryServiceV2.php",
        "pricing": "{base}/pstd/productpricingconfiguration/PricingAndConfigurationService.php",
        "media": "{base}/pstd/mediacontent1.1/MediaContentService.php",
        "bulk_data": "{base}/bulk-data/BulkDataService.php",
    },
    "alphabroder": {
        "label": "alphabroder",
        "product_data": "{base}/promostandards/ProductDataService/v2.0.0/ProductDataService.svc",
        "inventory": "{base}/promostandards/InventoryService/v2.0.0/InventoryService.svc",
        "pricing": "{base}/promostandards/PricingAndConfigurationService/v1.0.0/PricingAndConfigurationService.svc",
        "media": "{base}/promostandards/MediaContentService/v1.1.0/MediaContentService.svc",
        "bulk_data": "{base}/promostandards/BulkDataService/v1.0.0/BulkDataService.svc",
    },
    "generic": {
        "label": "Generic PromoStandards",
        "product_data": "{base}/productdata/v2/ProductDataService.svc",
        "inventory": "{base}/inventory/v2/InventoryService.svc",
        "pricing": "{base}/pricingandconfiguration/v1/PricingAndConfigurationService.svc",
        "media": "{base}/mediacontent/v1/MediaContentService.svc",
        "bulk_data": "{base}/bulkdata/v1/BulkDataService.svc",
    }
}


def generate_endpoints(base_url: str, style: str) -> Dict[str, str]:
    """Generate service endpoints from base URL and style."""
    base = base_url.rstrip('/')
    pattern = SUPPLIER_PATTERNS.get(style, SUPPLIER_PATTERNS['generic'])
    return {k: v.format(base=base) for k, v in pattern.items() if k != 'label'}


# asyncio.to_thread propagates this per-job context to supplier calls.
request_context = contextvars.ContextVar('supplier_request_context', default=None)


class SupplierAPIError(ValueError):
    def __init__(self, code, message, retryable=False, attempts=1):
        super().__init__(message)
        self.code, self.retryable, self.attempts = code, retryable, attempts


def error_result(error):
    return {'success': False, 'error': str(error),
            'error_code': getattr(error, 'code', 'SUPPLIER_ERROR'),
            'retryable': getattr(error, 'retryable', False),
            'attempts': getattr(error, 'attempts', 1)}


def _soap_call(endpoint: str, action: str, body_xml: str, timeout: int = 30):
    """Bounded retries for reads; no automatic retry for account-limited BulkData."""
    parsed = urlsplit(str(endpoint or ''))
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise SupplierAPIError('ENDPOINT', 'Configure a valid supplier service URL without embedded credentials.')
    envelope = ('<?xml version="1.0" encoding="utf-8"?>'
                '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                '<soap:Body>' + body_xml + '</soap:Body></soap:Envelope>')
    headers = {'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': action,
               'User-Agent': 'SupplierHub/1.0 PromoStandards Client'}
    context = request_context.get() or {}
    stop = context.get('stop')
    max_attempts = 1 if action == 'getBulkData' else 2
    for attempt in range(1, max_attempts + 1):
        if stop and stop.is_set():
            raise SupplierAPIError('CANCELLED', 'Stop requested; supplier request cancelled before the next attempt.')
        response = None
        try:
            response = requests.post(endpoint, data=envelope.encode('utf-8'), headers=headers,
                                     timeout=(10, timeout), allow_redirects=False)
            status = response.status_code
            if status in (401, 403):
                raise SupplierAPIError('ACCESS_DENIED', f'Supplier returned HTTP {status}. Check account access and any IP restrictions with the supplier; the cause is not confirmed.')
            if status == 404 or 300 <= status < 400:
                raise SupplierAPIError('ENDPOINT', f'Supplier returned HTTP {status}. Check the direct SOAP service URL.')
            if status == 429:
                raise SupplierAPIError('RATE_LIMIT', 'Supplier rate limit reached. Wait before manually retrying.')
            if status in (502, 503, 504):
                raise SupplierAPIError('UNAVAILABLE', f'Supplier temporarily unavailable (HTTP {status}).', True, attempt)
            # SOAP faults may be returned with HTTP 500, so parse them before rejecting HTTP errors.
            try:
                root = etree.fromstring(response.content, parser=etree.XMLParser(resolve_entities=False, no_network=True))
            except etree.XMLSyntaxError:
                raise SupplierAPIError('INVALID_RESPONSE', f'Supplier returned a non-XML or malformed response (HTTP {status}).')
            body = root.find('{http://schemas.xmlsoap.org/soap/envelope/}Body')
            if body is None:
                raise SupplierAPIError('INVALID_RESPONSE', 'Supplier response has no SOAP 1.1 body. Check the service endpoint/version.')
            fault = body.find('{http://schemas.xmlsoap.org/soap/envelope/}Fault')
            if fault is not None:
                # Do not expose vendor fault text that could echo credentials or request bodies.
                raise SupplierAPIError('SOAP_FAULT', 'Supplier returned a SOAP fault. Check credentials, service version and request configuration.')
            for element in body.iter():
                tag = etree.QName(element).localname if isinstance(element.tag, str) else ''
                if tag.casefold() in ('errormessage', 'servicemessage'):
                    fields = {etree.QName(child).localname: (child.text or '').strip() for child in element.iter() if isinstance(child.tag, str)}
                    fields = {key.casefold(): value for key, value in fields.items()}
                    code = fields.get('code', '')
                    severity = fields.get('severity', '').casefold()
                    is_atc = parsed.hostname == 'edi.atc-apparel.com'
                    # ATC's guide: pricing success uses code 200 in ErrorMessage;
                    # media success uses lowercase errorMessage with code 0.
                    if severity != 'error' and (code == '0' or (is_atc and code == '200')):
                        continue
                    if (tag.casefold() == 'errormessage' or severity == 'error'
                            or code == '125' or (is_atc and code in ('100','105','110','115','120','130','135','140','145','150','300','400','999'))):
                        error_code = 'RATE_LIMIT' if code == '125' and action.casefold() == 'getbulkdata' else 'SERVICE_ERROR'
                        description = (
                            fields.get('description')
                            or fields.get('message')
                            or 'No description supplied'
                        )

                        # Remove request credentials if the supplier echoes them.
                        request_parser = etree.XMLParser(
                            resolve_entities=False,
                            no_network=True,
                        )
                        request_root = etree.fromstring(
                            body_xml.encode('utf-8'),
                            parser=request_parser,
                        )
                        for node in request_root.iter():
                            if isinstance(node.tag, str):
                                name = etree.QName(node).localname.lower()
                                if name in ('id', 'password') and node.text:
                                    description = description.replace(
                                        node.text, '[redacted]'
                                    )

                        description = ' '.join(description.split())[:500]
                        raise SupplierAPIError(
                            error_code,
                            f'Supplier service code {code or "unknown"}: {description}',
                        )
            if status >= 400:
                raise SupplierAPIError('HTTP_ERROR', f'Supplier returned HTTP {status}.')
            return body
        except requests.exceptions.SSLError:
            error = SupplierAPIError('TLS', 'TLS/certificate verification failed. Check the endpoint and network certificates; certificate verification remains enabled.')
        except requests.exceptions.Timeout:
            error = SupplierAPIError('TIMEOUT', 'Supplier connection/read timed out. Check network access and supplier availability.', True, attempt)
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError):
            error = SupplierAPIError('CONNECTION_RESET', 'Supplier connection failed or was reset. Check network/VPN, endpoint and supplier access restrictions.', True, attempt)
        except SupplierAPIError as exc:
            error = exc
        finally:
            if response is not None:
                response.close()
        error.attempts = attempt
        if not error.retryable or attempt == max_attempts:
            raise error
        callback = context.get('on_retry')
        if callback:
            callback({'attempt': attempt + 1, 'code': error.code, 'message': str(error)})
        delay = min(2 ** attempt, 4)
        if stop:
            if stop.wait(delay):
                raise SupplierAPIError('CANCELLED', 'Stop requested during retry backoff.')
        else:
            time.sleep(delay)
    raise SupplierAPIError('SUPPLIER_ERROR', 'Supplier request failed.')


def _get_text(el, path, namespaces=None, default=''):
    """Safely extract text from XML element."""
    if el is None:
        return default
    found = el.find(path, namespaces) if namespaces else el.find(path)
    if found is not None and found.text:
        return found.text.strip()
    return default


def _get_int(el, path, namespaces=None, default=0):
    """Safely extract int from XML element."""
    text = _get_text(el, path, namespaces, '')
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return default


def _get_float(el, path, namespaces=None, default=0.0):
    """Safely extract float from XML element."""
    text = _get_text(el, path, namespaces, '')
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


class PromoStandardsConnector:
    """Multi-supplier PromoStandards connector using raw SOAP XML."""

    def __init__(self, supplier_config: dict):
        self.supplier_id = supplier_config.get('id', '')
        self.account_id = str(supplier_config.get('account_number', ''))
        self.password = supplier_config.get('password', '')
        self.media_password = supplier_config.get('media_password', '') or self.password
        self.bulk_data_email = str(supplier_config.get('bulk_data_email') or (self.password if '@' in self.password else '')).strip()
        configured_services = supplier_config.get('services') or {}
        if isinstance(configured_services, str):
            configured_services = json.loads(configured_services)
        self.services = dict(configured_services)
        self.endpoint_style = supplier_config.get('endpoint_style', '')
        self.base_url = supplier_config.get('api_base_url', '')
        
        # XML-escaped versions for use in SOAP requests
        self._safe_account_id = xml_escape(self.account_id)
        self._safe_password = xml_escape(self.password)
        self._safe_media_password = xml_escape(self.media_password)

        # Auto-detect endpoint style from base URL if not set
        if not self.endpoint_style and self.base_url:
            base_lower = self.base_url.lower()
            if 'atc-apparel' in base_lower or 'sanmar' in base_lower:
                self.endpoint_style = 'atc'
            elif 'ssactivewear' in base_lower:
                self.endpoint_style = 'ss'
            elif 'alphabroder' in base_lower:
                self.endpoint_style = 'alphabroder'
            else:
                self.endpoint_style = 'generic'
            logger.debug(f"Auto-detected endpoint style: {self.endpoint_style}")

        # Explicit endpoint URLs also identify ATC when the style/base is absent.
        if any(urlsplit(str(url)).hostname == 'edi.atc-apparel.com'
               for url in self.services.values()):
            self.endpoint_style = 'atc'
        self.is_atc = self.endpoint_style == 'atc'
        self.country = 'CA' if self.is_atc else 'US'
        self.fob_id = str(supplier_config.get('fob_id') or '')
        if self.is_atc and self.fob_id not in ('', '1', '2', '4'):
            raise ValueError('ATC fob_id must be blank, 1, 2 or 4.')

        # Auto-generate endpoints if not explicitly set
        if not self.services and self.base_url and self.endpoint_style:
            self.services = generate_endpoints(self.base_url, self.endpoint_style)
            logger.info(f"Auto-generated endpoints for {self.endpoint_style}: {list(self.services.keys())}")

        # Ensure bulk_data endpoint exists if we have a base URL and style
        if 'bulk_data' not in self.services and self.base_url and self.endpoint_style:
            all_endpoints = generate_endpoints(self.base_url, self.endpoint_style)
            if 'bulk_data' in all_endpoints:
                self.services['bulk_data'] = all_endpoints['bulk_data']

        # Strip ?wsdl from endpoints (we need service endpoints, not WSDL URLs)
        for key in list(self.services.keys()):
            url = self.services[key]
            if url.endswith('?wsdl') or url.endswith('?WSDL'):
                self.services[key] = url.rsplit('?', 1)[0]

    def _get_endpoint(self, service_name: str) -> str:
        url = self.services.get(service_name)
        if not url:
            raise SupplierAPIError('ENDPOINT', f"No endpoint configured for '{service_name}'. Configure service URLs in Supplier settings.")
        return url

    def test_connection(self) -> dict:
        """Test connectivity to the product data endpoint."""
        try:
            endpoint = self._get_endpoint('product_data')
            optional_fields = '<ns:partId></ns:partId><ns:lineName></ns:lineName>' if self.is_atc else ''
            body_xml = f'''<ns:GetProductSellableRequest xmlns:ns="{NS['pd']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:localizationCountry>{self.country}</ns:localizationCountry>
              <ns:localizationLanguage>en</ns:localizationLanguage>
              <ns:productId>ALL</ns:productId>
              {optional_fields}
              <ns:isSellable>true</ns:isSellable>
            </ns:GetProductSellableRequest>'''
            body = _soap_call(endpoint, 'getProductSellable', body_xml, timeout=15)

            return {'success': True, 'connected': True, 'message': 'Connection successful'}
        except ConnectionError as e:
            return {**error_result(e), 'connected': False, 'message': str(e)}
        except ValueError as e:
            return {**error_result(e), 'connected': False, 'message': str(e)}
        except Exception as e:
            return {'success': False, 'connected': False, 'message': f'Connection failed: {str(e)}'}

    def get_sellable_products(self) -> dict:
        try:
            endpoint = self._get_endpoint('product_data')
            optional_fields = '<ns:partId></ns:partId><ns:lineName></ns:lineName>' if self.is_atc else ''
            body_xml = f'''<ns:GetProductSellableRequest xmlns:ns="{NS['pd']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:localizationCountry>{self.country}</ns:localizationCountry>
              <ns:localizationLanguage>en</ns:localizationLanguage>
              <ns:productId>ALL</ns:productId>
              {optional_fields}
              <ns:isSellable>true</ns:isSellable>
            </ns:GetProductSellableRequest>'''

            body = _soap_call(endpoint, 'getProductSellable', body_xml)
            products = []

            # Parse response - try both namespaced and unnamespaced
            for ps in body.iter():
                if 'ProductSellable' in ps.tag and 'Array' not in ps.tag and 'Request' not in ps.tag and 'Response' not in ps.tag:
                    pid = None
                    part_id = None
                    for child in ps:
                        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if tag == 'productId' and child.text:
                            raw_pid = child.text.strip()
                            # Extract base product ID - some APIs return "SKU(Color,Size,X)" format
                            # We need just "SKU" for getProduct calls
                            if '(' in raw_pid:
                                pid = raw_pid.split('(')[0]
                            else:
                                pid = raw_pid
                        elif tag == 'partId' and child.text:
                            part_id = child.text.strip()
                    if pid:
                        products.append({'product_id': pid, 'part_id': part_id})

            logger.info(f"Got {len(products)} sellable items")
            return {'success': True, 'products': products}
        except (ConnectionError, ValueError) as e:
            return error_result(e)
        except Exception as e:
            logger.error(f"getProductSellable error: {e}")
            return error_result(e)

    def get_product(self, product_id: str) -> dict:
        try:
            endpoint = self._get_endpoint('product_data')
            safe_product_id = xml_escape(product_id)
            optional_fields = '<ns:partId></ns:partId><ns:colorName></ns:colorName>' if self.is_atc else ''
            body_xml = f'''<ns:GetProductRequest xmlns:ns="{NS['pd']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:localizationCountry>{self.country}</ns:localizationCountry>
              <ns:localizationLanguage>en</ns:localizationLanguage>
              <ns:productId>{safe_product_id}</ns:productId>
              {optional_fields}
            </ns:GetProductRequest>'''

            body = _soap_call(endpoint, 'getProduct', body_xml)

            product_element = next((el for el in body.iter()
                                    if isinstance(el.tag, str) and etree.QName(el).localname == 'Product'), None)
            if product_element is None:
                raise SupplierAPIError('INVALID_RESPONSE', 'Supplier returned no Product record.')

            product = {
                'supplier_sku': product_id,
                'product_name': '', 'description': '', 'brand': '', 'category': '',
                'variants': [], 'is_closeout': False
            }

            # Helper to get clean text (handles mixed content)
            def get_clean_text(element):
                if element is None:
                    return ''
                # Get direct text content only, not nested elements
                text = element.text
                if text and isinstance(text, str):
                    clean = text.strip()
                    # Skip if it looks like array/object serialization
                    if clean and clean not in ['Array', 'Object', '[]', '{}']:
                        return clean
                return ''

            # Extract product data from response
            for el in product_element.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'productName':
                    text = get_clean_text(el)
                    if text and not product['product_name']:
                        product['product_name'] = text
                elif tag == 'description':
                    text = get_clean_text(el)
                    if text and not product['description']:
                        product['description'] = text
                elif tag == 'productBrand':
                    text = get_clean_text(el)
                    if text:
                        product['brand'] = text
                elif tag == 'isCloseout':
                    text = get_clean_text(el)
                    if text:
                        product['is_closeout'] = text.lower() == 'true'

            # Extract categories
            categories = []
            for el in product_element.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'category' and el.text:
                    categories.append(el.text.strip())
            if categories:
                product['category'] = ', '.join(dict.fromkeys(categories))

            # Extract variants (ProductPart elements)
            for el in product_element.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'ProductPart':
                    variant = {'variant_sku': '', 'color': '', 'size': '', 'country_of_origin': '', 'lead_time': ''}
                    
                    # Get direct children of ProductPart
                    for child in el:
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'partId' and child.text:
                            variant['variant_sku'] = child.text.strip()
                        elif ctag == 'countryOfOrigin' and child.text:
                            variant['country_of_origin'] = child.text.strip()
                        elif ctag == 'leadTime' and child.text:
                            variant['lead_time'] = child.text.strip()
                        elif ctag == 'ColorArray':
                            # Color is nested: ColorArray/Color/colorName
                            for color_el in child:
                                for color_child in color_el:
                                    cctag = color_child.tag.split('}')[-1] if '}' in color_child.tag else color_child.tag
                                    if cctag == 'colorName' and color_child.text:
                                        variant['color'] = color_child.text.strip()
                                        break
                        elif ctag == 'ApparelSize':
                            # Size is nested: ApparelSize/labelSize
                            for size_child in child:
                                stag = size_child.tag.split('}')[-1] if '}' in size_child.tag else size_child.tag
                                if stag == 'labelSize' and size_child.text:
                                    variant['size'] = size_child.text.strip()
                                    break
                    
                    # Only add variants with a valid SKU (skip 'DEFAULT' placeholder)
                    if variant['variant_sku'] and variant['variant_sku'] != 'DEFAULT':
                        product['variants'].append(variant)

            return {'success': True, 'product': product}
        except (ConnectionError, ValueError) as e:
            return error_result(e)
        except Exception as e:
            logger.error(f"getProduct error [{product_id}]: {e}")
            return error_result(e)

    def get_inventory(self, product_id: str) -> dict:
        try:
            endpoint = self._get_endpoint('inventory')
            safe_product_id = xml_escape(product_id)
            body_xml = f'''<ns:GetInventoryLevelsRequest xmlns:ns="{NS['inv']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:productId>{safe_product_id}</ns:productId>
            </ns:GetInventoryLevelsRequest>'''

            body = _soap_call(endpoint, 'getInventoryLevels', body_xml)
            inventory = []

            # Helper to extract quantity value from nested Quantity element
            def get_quantity_value(parent_el):
                """Extract value from <Quantity><value>X</value></Quantity> structure"""
                for child in parent_el.iter():
                    ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if ctag == 'value' and child.text:
                        try:
                            value = float(child.text.strip())
                            if math.isfinite(value) and value >= 0 and value.is_integer():
                                return int(value)
                        except ValueError:
                            pass
                return None

            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'PartInventory':
                    item = {'part_id': '', 'part_color': '', 'label_size': '', 'quantity_available': None, 'warehouses': []}
                    for child in el:
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'partId' and child.text:
                            item['part_id'] = child.text.strip()
                        elif ctag == 'partColor' and child.text:
                            item['part_color'] = child.text.strip()
                        elif ctag == 'labelSize' and child.text:
                            item['label_size'] = child.text.strip()
                        elif ctag == 'quantityAvailable':
                            # Handle nested <Quantity><value>X</value></Quantity> structure
                            item['quantity_available'] = get_quantity_value(child)
                        elif ctag == 'InventoryLocationArray':
                            for loc_el in child:
                                loc_tag = loc_el.tag.split('}')[-1] if '}' in loc_el.tag else loc_el.tag
                                if loc_tag == 'InventoryLocation':
                                    wh = {'id': '', 'name': '', 'quantity': None}
                                    for loc_child in loc_el:
                                        ltag = loc_child.tag.split('}')[-1] if '}' in loc_child.tag else loc_child.tag
                                        if ltag == 'inventoryLocationId' and loc_child.text:
                                            wh['id'] = loc_child.text.strip()
                                        elif ltag == 'inventoryLocationName' and loc_child.text:
                                            wh['name'] = loc_child.text.strip()
                                        elif ltag == 'inventoryLocationQuantity':
                                            # Handle nested <Quantity><value>X</value></Quantity> structure
                                            wh['quantity'] = get_quantity_value(loc_child)
                                    if wh['id']:
                                        item['warehouses'].append(wh)
                    if item['part_id']:
                        inventory.append(item)

            return {'success': True, 'inventory': inventory}
        except (ConnectionError, ValueError) as e:
            return error_result(e)
        except Exception as e:
            logger.error(f"getInventoryLevels error [{product_id}]: {e}")
            return error_result(e)

    def get_pricing(self, product_id: str) -> dict:
        try:
            endpoint = self._get_endpoint('pricing')
            safe_product_id = xml_escape(product_id)
            is_atc = self.is_atc
            currency = 'CAD' if is_atc else 'USD'
            country = 'CA' if is_atc else 'US'
            price_type = 'CUSTOMER' if is_atc else 'Net'
            language = 'EN' if is_atc else 'en'
            configuration = 'BLANK' if is_atc else 'Blank'
            part_field = '<ns:partId></ns:partId>' if is_atc else ''
            body_xml = f'''<ns:GetConfigurationAndPricingRequest xmlns:ns="{NS['ppc']}">
              <ns:wsVersion>1.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:productId>{safe_product_id}</ns:productId>
              {part_field}
              <ns:currency>{currency}</ns:currency>
              <ns:fobId>{xml_escape(self.fob_id)}</ns:fobId>
              <ns:priceType>{price_type}</ns:priceType>
              <ns:localizationCountry>{country}</ns:localizationCountry>
              <ns:localizationLanguage>{language}</ns:localizationLanguage>
              <ns:configurationType>{configuration}</ns:configurationType>
            </ns:GetConfigurationAndPricingRequest>'''

            body = _soap_call(endpoint, 'GetConfigurationAndPricing', body_xml)
            pricing = []

            # Find all Part elements
            for part_el in body.iter():
                tag = part_el.tag.split('}')[-1] if '}' in part_el.tag else part_el.tag
                if tag == 'Part':
                    part_data = {'part_id': '', 'prices': []}
                    
                    # Get direct children of Part
                    for child in part_el:
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'partId' and child.text:
                            part_data['part_id'] = child.text.strip()
                        elif ctag == 'PartPriceArray':
                            # Iterate over PartPrice elements
                            for pp in child:
                                price = {'min_quantity': 0, 'price': 0.0, 'uom': ''}
                                for pchild in pp:
                                    ptag = pchild.tag.split('}')[-1] if '}' in pchild.tag else pchild.tag
                                    if ptag == 'minQuantity' and pchild.text:
                                        try:
                                            price['min_quantity'] = int(float(pchild.text.strip()))
                                        except ValueError:
                                            pass
                                    elif ptag == 'price' and pchild.text:
                                        try:
                                            price['price'] = float(pchild.text.strip())
                                        except ValueError:
                                            pass
                                    elif ptag in ('priceEffectiveDate', 'priceExpiryDate', 'discountCode'):
                                        price[ptag] = (pchild.text or '').strip()
                                    elif ptag == 'priceUom' and pchild.text:
                                        price['uom'] = pchild.text.strip()
                                if math.isfinite(price['price']) and price['price'] > 0:
                                    part_data['prices'].append(price)
                    
                    if part_data['part_id'] and part_data['prices']:
                        pricing.append(part_data)

            return {'success': True, 'pricing': pricing}
        except (ConnectionError, ValueError) as e:
            return error_result(e)
        except Exception as e:
            logger.error(f"GetConfigurationAndPricing error [{product_id}]: {e}")
            return error_result(e)

    def get_media(self, product_id: str) -> dict:
        try:
            endpoint = self._get_endpoint('media')
            safe_product_id = xml_escape(product_id)
            # ATC 1.1 puts common fields in SharedObjects; 1.2 uses the
            # service namespace and mediaType=media (guide pp. 74, 77-80).
            version = '1.2.0' if self.is_atc and '/mediacontent1.2/' in urlsplit(endpoint).path else '1.1.0'
            prefix = 'so' if self.is_atc and version == '1.1.0' else 'ns'
            media_type = 'media' if version == '1.2.0' else 'Image'
            culture = '' if version == '1.2.0' else 'en-US'
            class_type = '' if self.is_atc else '0'
            body_xml = f'''<ns:GetMediaContentRequest xmlns:ns="{NS['mc']}" xmlns:so="{NS['mc_so']}">
              <{prefix}:wsVersion>{version}</{prefix}:wsVersion>
              <{prefix}:id>{self._safe_account_id}</{prefix}:id>
              <{prefix}:password>{self._safe_media_password}</{prefix}:password>
              <{prefix}:cultureName>{culture}</{prefix}:cultureName>
              <{prefix}:mediaType>{media_type}</{prefix}:mediaType>
              <{prefix}:productId>{safe_product_id}</{prefix}:productId>
              <{prefix}:partId></{prefix}:partId>
              <ns:classType>{class_type}</ns:classType>
            </ns:GetMediaContentRequest>'''

            body = _soap_call(endpoint, 'getMediaContent', body_xml)
            media = []

            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'MediaContent' and 'Array' not in el.tag:
                    item = {'url': '', 'media_type': 'Image', 'width': None, 'height': None, 'color': '', 'description': ''}
                    for child in el:
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'url' and child.text:
                            item['url'] = child.text.strip()
                        elif ctag == 'mediaType' and child.text:
                            item['media_type'] = child.text.strip()
                        elif ctag == 'width' and child.text:
                            try:
                                item['width'] = int(child.text.strip())
                            except ValueError:
                                pass
                        elif ctag == 'height' and child.text:
                            try:
                                item['height'] = int(child.text.strip())
                            except ValueError:
                                pass
                        elif ctag == 'color' and child.text:
                            item['color'] = child.text.strip()
                        elif ctag == 'description' and child.text:
                            item['description'] = child.text.strip()
                    
                    from media_links import xml_links
                    item.update(xml_links(el))
                    class_types = []
                    for node in el.iter():
                        if isinstance(node.tag, str) and etree.QName(node).localname == 'ClassType':
                            values = {etree.QName(child).localname: (child.text or '').strip()
                                      for child in node if isinstance(child.tag, str)}
                            class_types.append(values)
                    item['class_types'] = class_types
                    item['is_primary'] = any(v.get('classTypeId') == '1006' for v in class_types)
                    item['type'] = 'image'  # ATC 1.2 calls image records "media".
                    # Handle case where URL field contains multiple URLs (newline-separated)
                    if item['url']:
                        url_lines = [u.strip() for u in item['url'].split('\n') if u.strip()]
                        if len(url_lines) > 1:
                            # Multiple URLs in single field - create separate media items
                            for url in url_lines:
                                if url.startswith(('http://', 'https://')):
                                    media.append({**item, 'url': url})
                        else:
                            if item['url'].startswith(('http://', 'https://')):
                                media.append(item)

            linked=sum(bool(i.get("color") or i.get("part_ids")) for i in media)
            logger.info(f"Got {len(media)} media items for {product_id}; {linked} carry supplier colour/part associations")
            return {'success': True, 'media': media}
        except (ConnectionError, ValueError) as e:
            return error_result(e)
        except Exception as e:
            logger.error(f"getMediaContent error [{product_id}]: {e}")
            return error_result(e)


    def get_bulk_data(self) -> dict:
        """
        Get bulk product data using BulkData Service 1.0.
        This endpoint returns comprehensive product data including image URLs
        that can be downloaded (unlike MediaContent URLs which are hotlink-blocked).
        
        Returns product data with: productId, productName, style, size, color, brand, 
        weight, quantity, price, salePrice, and importantly - image URLs.
        
        IMPORTANT: Limited to once per day per account. Subsequent calls return error 125.
        """
        try:
            endpoint = self._get_endpoint('bulk_data')
            
            # BulkData uses a different namespace than other PromoStandards services
            body_xml = f'''<ns:GetBulkDataRequest xmlns:ns="{NS['bd']}">
              <ns:wsVersion>1.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{xml_escape(self.bulk_data_email) if self.is_atc else self._safe_password}</ns:password>
            </ns:GetBulkDataRequest>'''
            
            logger.info("Calling supplier BulkData API")
            body = _soap_call(endpoint, 'getBulkData', body_xml, timeout=120)  # Longer timeout for large response
            
            from bulk_data import parse_bulk_xml
            result = parse_bulk_xml(etree.tostring(body, encoding='utf-8'))
            logger.info("BulkData returned %s variants", result['count'])
            return result

        except (ConnectionError, ValueError) as e:
            return error_result(e)
        except Exception as e:
            logger.error(f"getBulkData error: {e}")
            return error_result(e)

    def download_image(self, image_url: str, save_path: str = None) -> dict:
        """
        Download an image from a URL and optionally save it locally.
        This is used for BulkData images which can be downloaded (not hotlink-blocked).
        
        Args:
            image_url: The URL of the image to download
            save_path: Optional local path to save the image
            
        Returns:
            dict with 'success', 'image_data' (base64), and optionally 'saved_path'
        """
        import base64
        import os
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/*,*/*;q=0.8',
            }
            
            response = requests.get(image_url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return {'success': False, 'error': f'HTTP {response.status_code}'}
            
            content_type = response.headers.get('content-type', '').lower()
            
            # Verify it's an image
            is_image = 'image' in content_type
            if not is_image and response.content:
                magic = response.content[:8]
                is_image = (magic.startswith(b'\xff\xd8\xff') or  # JPEG
                           magic.startswith(b'\x89PNG') or        # PNG
                           magic.startswith(b'GIF8') or           # GIF
                           magic.startswith(b'RIFF'))             # WebP
            
            if not is_image:
                return {'success': False, 'error': 'Response is not an image'}
            
            image_base64 = base64.b64encode(response.content).decode('utf-8')
            result = {'success': True, 'image_data': image_base64, 'size': len(response.content)}
            
            # Save to file if path provided
            if save_path:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                result['saved_path'] = save_path
                logger.info(f"Saved image to {save_path}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error downloading image {image_url}: {e}")
            return error_result(e)
