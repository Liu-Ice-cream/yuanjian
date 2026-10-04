from django.test import TestCase
from django.urls import reverse


class OpenSearchViewTestCase(TestCase):
    def test_opensearch_configuration(self):
        response = self.client.get(reverse("linkding:opensearch"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["content-type"], "application/opensearchdescription+xml"
        )

        base_url = "http://testserver"
        expected_content = f"""
            <OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/" xmlns:moz="http://www.mozilla.org/2006/browser/search/">
                <ShortName>源笺</ShortName>
                <Description>帮助研究者把收藏的资料转化成可复用的研究材料。</Description>
                <InputEncoding>UTF-8</InputEncoding>
                <Image width="16" height="16" type="image/svg+xml">{base_url}/static/yuanjian.svg</Image>
                <Url type="text/html" template="{base_url}/research/?client=opensearch&amp;q={{searchTerms}}"/>
            </OpenSearchDescription>
        """
        content = response.content.decode()
        self.assertXMLEqual(content, expected_content)
