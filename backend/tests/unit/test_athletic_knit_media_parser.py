import pytest

from multi_supplier.media_parser import parse_media


SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
MEDIA = "http://www.promostandards.org/WSDL/MediaService/1.0.0/"
SHARED = "http://www.promostandards.org/WSDL/MediaService/1.0.0/SharedObjects/"


def response(records):
    items = "".join(
        f"""
        <media:MediaContent>
          <shared:productId>AK-100</shared:productId>
          <shared:partId>{part}</shared:partId>
          <media:url>{url}</media:url>
          <shared:mediaType>Image</shared:mediaType>
          <media:singlePart>{single}</media:singlePart>
          <media:fileSize>1234</media:fileSize>
        </media:MediaContent>
        """
        for part, url, single in records
    )
    return f"""
    <soap:Envelope xmlns:soap="{SOAP}" xmlns:media="{MEDIA}" xmlns:shared="{SHARED}">
      <soap:Body><media:GetMediaContentResponse>{items}</media:GetMediaContentResponse></soap:Body>
    </soap:Envelope>
    """


def test_media_deduplicates_urls_and_preserves_all_part_associations():
    url = "https://cdn.example.test/ak100-front.jpg"
    result = parse_media(response([
        ("AK-100-BLK-S", url, "false"),
        ("AK-100-BLK-M", url, "true"),
        ("AK-100-BLK-L", "https://cdn.example.test/ak100-back.jpg", "false"),
    ]))
    assert result["record_count"] == 3
    assert result["unique_media_count"] == 2
    first = result["unique_media"][0]
    assert first["url"] == url
    assert first["part_ids"] == ["AK-100-BLK-S", "AK-100-BLK-M"]
    assert first["single_part"] is True


def test_raises_on_soap_fault():
    xml = f"""
    <soap:Envelope xmlns:soap="{SOAP}">
      <soap:Body><soap:Fault><faultstring>Invalid account</faultstring></soap:Fault></soap:Body>
    </soap:Envelope>
    """
    with pytest.raises(ValueError, match="Invalid account"):
        parse_media(xml)


def test_empty_media_response_is_a_valid_empty_result():
    xml = f"""
    <soap:Envelope xmlns:soap="{SOAP}" xmlns:media="{MEDIA}">
      <soap:Body><media:GetMediaContentResponse/></soap:Body>
    </soap:Envelope>
    """
    result = parse_media(xml)
    assert result["records"] == []
    assert result["unique_media"] == []
    assert result["unique_media_count"] == 0
