from django.test import TestCase, override_settings


class MetadataViewTestCase(TestCase):
    def test_default_manifest(self):
        response = self.client.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest["name"], "源笺")
        self.assertEqual(manifest["start_url"], "/research/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["share_target"]["action"], "/research/materials/new")
        self.assertEqual(manifest["share_target"]["method"], "GET")
        self.assertEqual(manifest["share_target"]["params"]["url"], "url")
        self.assertEqual(manifest["icons"][0]["src"], "/static/yuanjian.svg")
        self.assertEqual(manifest["display"], "standalone")

    @override_settings(LD_CONTEXT_PATH="yuanjian/")
    def test_manifest_respects_context_path(self):
        response = self.client.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest["scope"], "/yuanjian/")
        self.assertEqual(manifest["start_url"], "/yuanjian/research/")
        for item in manifest["icons"]:
            self.assertTrue(item["src"].startswith("/yuanjian/static/"))
        for item in manifest["shortcuts"]:
            self.assertTrue(item["url"].startswith("/yuanjian/research/"))
        self.assertEqual(
            manifest["share_target"]["action"], "/yuanjian/research/materials/new"
        )
