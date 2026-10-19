import logging

from xml.sax.saxutils import escape

import requests

import json


logger = logging.getLogger(__name__)


SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"

PRODUCT_NS = (
    "http://www.promostandards.org/"
    "WSDL/ProductDataService/2.0.0/"
)

PRODUCT_SHARED_NS = (
    "http://www.promostandards.org/"
    "WSDL/ProductDataService/2.0.0/SharedObjects/"
)

INVENTORY_NS = (
    "http://www.promostandards.org/"
    "WSDL/Inventory/2.0.0/"
)

INVENTORY_SHARED_NS = (
    "http://www.promostandards.org/"
    "WSDL/Inventory/2.0.0/SharedObjects/"
)

MEDIA_NS = (
    "http://www.promostandards.org/"
    "WSDL/MediaService/1.0.0/"
)

MEDIA_SHARED_NS = (
    "http://www.promostandards.org/"
    "WSDL/MediaService/1.0.0/SharedObjects/"
)

class AthleticKnitClient:

    def __init__(self,supplier):
        services=supplier.get('services') or {}
        if isinstance(services,str):services=json.loads(services)
        self.account_id=supplier.get('account_number') or ''
        self.password=supplier.get('password') or ''
        self.product_url=services.get('product_data') or ''
        self.inventory_url=services.get('inventory') or ''
        self.pricing_url=services.get('pricing') or ''
        self.media_url=services.get('media') or ''
        self.country='CA';self.language='en';self.debug=False
        if not self.product_url:raise ValueError('Enter the Athletic Knit Product Data URL')

    def _soap_post(
        self,
        endpoint: str,
        body_xml: str,
        soap_action: str
    ) -> str:

        envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
    <soapenv:Envelope
        xmlns:soapenv="{SOAP_NS}">
        <soapenv:Header/>
        <soapenv:Body>
            {body_xml}
        </soapenv:Body>
    </soapenv:Envelope>
    """

        headers = {
            "Content-Type": "text/xml; charset=UTF-8",
            "Accept": "*/*",
            "SOAPAction": soap_action,
        }

        # ---------------------------------
        # DEBUG REQUEST OUTPUT
        # ---------------------------------

        if self.debug:

            print()
            print("=" * 70)
            print("ATHLETIC KNIT REQUEST")
            print("=" * 70)

            print(f"URL: {endpoint}")
            print(f"SOAPAction: {soap_action}")

            print()
            print("Request Headers:")

            for key, value in headers.items():
                print(
                    f"  {key}: {value}"
                )

            print()
            print("Sending request...")

        response = requests.post(
            endpoint,
            data=envelope.encode("utf-8"),
            headers=headers,
            timeout=60,
            allow_redirects=True
        )

        # ---------------------------------
        # SHORT NORMAL LOG
        # ---------------------------------

        print(
            f"Athletic Knit "
            f"{soap_action} -> "
            f"HTTP {response.status_code}"
        )

        # ---------------------------------
        # DEBUG RESPONSE OUTPUT
        # ---------------------------------

        if self.debug:

            print()
            print("=" * 70)
            print("ATHLETIC KNIT RESPONSE")
            print("=" * 70)

            print(
                f"HTTP Status: "
                f"{response.status_code}"
            )

            print(
                f"Final URL: "
                f"{response.url}"
            )

            print()
            print("Response Headers:")

            for key, value in (
                response.headers.items()
            ):

                print(
                    f"  {key}: {value}"
                )

        # ---------------------------------
        # ERROR HANDLING
        # ---------------------------------

        if response.status_code >= 400:

            if self.debug:

                print()
                print("Response preview:")
                print(
                    response.text[:2000]
                )

            server = response.headers.get(
                "Server",
                ""
            )

            cf_ray = response.headers.get(
                "CF-RAY",
                ""
            )

            if (
                "cloudflare" in server.lower()
                or "Just a moment"
                in response.text
                or cf_ray
            ):

                raise ConnectionError(
                    "Request was blocked by "
                    "Cloudflare before reaching "
                    "the Athletic Knit "
                    "PromoStandards API. "
                    f"HTTP="
                    f"{response.status_code}, "
                    f"CF-RAY="
                    f"{cf_ray or 'unknown'}"
                )

            raise ConnectionError(
                f"Athletic Knit returned "
                f"HTTP "
                f"{response.status_code}: "
                f"{response.text[:1000]}"
            )

        return response.text

    def get_product_raw(
        self,
        product_id: str
    ) -> str:

        body = f"""
<ns:GetProductRequest
    xmlns:ns="{PRODUCT_NS}"
    xmlns:shar="{PRODUCT_SHARED_NS}">

    <shar:wsVersion>2.0.0</shar:wsVersion>

    <shar:id>{escape(self.account_id)}</shar:id>

    <shar:password>{escape(self.password)}</shar:password>

    <shar:localizationCountry>
        {escape(self.country)}
    </shar:localizationCountry>

    <shar:localizationLanguage>
        {escape(self.language)}
    </shar:localizationLanguage>

    <shar:productId>
        {escape(product_id)}
    </shar:productId>

</ns:GetProductRequest>
"""

        return self._soap_post(
            endpoint=self.product_url,
            body_xml=body,
            soap_action="getProduct"
        )

    def get_inventory_raw(
        self,
        product_id: str
    ) -> str:

        body = f"""
    <inv:GetInventoryLevelsRequest
        xmlns:inv="{INVENTORY_NS}"
        xmlns:shar="{INVENTORY_SHARED_NS}">

        <shar:wsVersion>2.0.0</shar:wsVersion>

        <shar:id>{escape(self.account_id)}</shar:id>

        <shar:password>{escape(self.password)}</shar:password>

        <shar:productId>{escape(product_id)}</shar:productId>

    </inv:GetInventoryLevelsRequest>
    """

        return self._soap_post(
            endpoint=self.inventory_url,
            body_xml=body,
            soap_action="getInventoryLevels"
        )

    def get_sellable_products_raw(self) -> str:

        body = f"""
    <ns:GetProductSellableRequest
        xmlns:ns="{PRODUCT_NS}"
        xmlns:shar="{PRODUCT_SHARED_NS}">

        <shar:wsVersion>2.0.0</shar:wsVersion>

        <shar:id>{escape(self.account_id)}</shar:id>

        <shar:password>{escape(self.password)}</shar:password>

        <shar:localizationCountry>
            {escape(self.country)}
        </shar:localizationCountry>

        <shar:localizationLanguage>
            {escape(self.language)}
        </shar:localizationLanguage>

        <shar:isSellable>true</shar:isSellable>

    </ns:GetProductSellableRequest>
    """

        return self._soap_post(
            endpoint=self.product_url,
            body_xml=body,
            soap_action="getProductSellable"
        )

    def get_media_raw(
        self,
        product_id: str
    ) -> str:

        body = f"""
    <ns:GetMediaContentRequest
        xmlns:ns="{MEDIA_NS}"
        xmlns:shar="{MEDIA_SHARED_NS}">

        <shar:wsVersion>2.0.0</shar:wsVersion>

        <shar:id>{escape(self.account_id)}</shar:id>

        <shar:password>{escape(self.password)}</shar:password>

        <shar:cultureName>en-CA</shar:cultureName>

        <shar:mediaType>Image</shar:mediaType>

        <shar:productId>
            {escape(product_id)}
        </shar:productId>

    </ns:GetMediaContentRequest>
    """

        return self._soap_post(
            endpoint=self.media_url,
            body_xml=body,
            soap_action="getMediaContent"
        )