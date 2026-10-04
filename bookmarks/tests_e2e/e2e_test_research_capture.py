from threading import Event
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect

from bookmarks.services.website_loader import WebsiteMetadata
from bookmarks.tests_e2e.helpers import LinkdingE2ETestCase
from research.models import ResearchProject


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class ResearchCaptureE2ETestCase(LinkdingE2ETestCase):
    def test_project_capture_metadata_and_pending_to_recorded(self):
        project = ResearchProject.objects.create(
            owner=self.get_or_create_test_user(), name="快速收集课题"
        )
        page = self.open(reverse("research:index") + f"?project={project.pk}")
        page.get_by_role("link", name="收集资料", exact=True).first.click()
        expect(page.get_by_label("所属课题:", exact=True)).to_have_value(
            str(project.pk)
        )
        page.get_by_label("原始链接:", exact=True).fill("https://example.com/capture")
        page.get_by_label("资料标题:", exact=True).fill("我的资料标题")
        result = WebsiteMetadata(
            "https://example.com/capture", "网站标题", "网站简介", None
        )
        with patch(
            "research.views.website_loader.load_website_metadata", return_value=result
        ):
            page.get_by_role("button", name="读取资料信息", exact=True).click()
            expect(page.get_by_label("简要介绍:", exact=True)).to_have_value("网站简介")
        expect(page.get_by_label("资料标题:", exact=True)).to_have_value("我的资料标题")
        page.get_by_role("button", name="保存研究资料").click()
        expect(
            page.get_by_role("heading", name="我的资料标题", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="← 返回研究资料", exact=True).click()
        page.get_by_role("navigation", name="资料整理状态").get_by_role(
            "link", name="待整理", exact=True
        ).click()
        expect(
            page.get_by_role("heading", name="我的资料标题", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="开始整理 →", exact=True).click()
        page.get_by_label("研究问题:", exact=True).fill("这份资料能帮助回答什么问题？")
        page.get_by_role("button", name="保存研究资料").click()
        page.get_by_role("link", name="← 返回研究资料", exact=True).click()
        tabs = page.get_by_role("navigation", name="资料整理状态")
        tabs.get_by_role("link", name="待整理", exact=True).click()
        expect(
            page.get_by_role("heading", name="我的资料标题", exact=True)
        ).to_have_count(0)
        tabs.get_by_role("link", name="已有研究记录", exact=True).click()
        expect(
            page.get_by_role("heading", name="我的资料标题", exact=True)
        ).to_be_visible()

    def test_metadata_failure_does_not_block_manual_save(self):
        page = self.open(reverse("research:material_new"))
        page.get_by_label("原始链接:", exact=True).fill("https://example.com/manual")
        with patch(
            "research.views.website_loader.load_website_metadata",
            return_value=WebsiteMetadata(
                "https://example.com/manual", None, None, None
            ),
        ):
            page.get_by_role("button", name="读取资料信息", exact=True).click()
            expect(
                page.locator("yuanjian-metadata").get_by_role("status")
            ).to_contain_text("仍可以手动填写并保存")
        page.get_by_label("资料标题:", exact=True).fill("手工收集的资料")
        page.get_by_role("button", name="保存研究资料").click()
        expect(
            page.get_by_role("heading", name="手工收集的资料", exact=True)
        ).to_be_visible()

    def test_typing_while_reading_is_preserved(self):
        page = self.open(reverse("research:material_new"))
        page.get_by_label("原始链接:", exact=True).fill("https://example.com/delayed")
        started, release = Event(), Event()

        def delayed_metadata(url, **kwargs):
            started.set()
            release.wait(timeout=10)
            return WebsiteMetadata(url, "网站标题", "延迟读取的简介", None)

        with patch(
            "research.views.website_loader.load_website_metadata",
            side_effect=delayed_metadata,
        ):
            try:
                page.get_by_role("button", name="读取资料信息", exact=True).click()
                self.assertTrue(started.wait(timeout=5))
                page.get_by_label("资料标题:", exact=True).fill("等待期间写下的标题")
                release.set()
                expect(page.get_by_label("简要介绍:", exact=True)).to_have_value(
                    "延迟读取的简介"
                )
                expect(page.get_by_label("资料标题:", exact=True)).to_have_value(
                    "等待期间写下的标题"
                )
            finally:
                release.set()

    def test_changed_url_discards_inflight_result(self):
        page = self.open(reverse("research:material_new"))
        page.get_by_label("原始链接:", exact=True).fill("https://example.com/old")
        started, release = Event(), Event()

        def delayed_metadata(url, **kwargs):
            started.set()
            release.wait(timeout=10)
            return WebsiteMetadata(url, "旧链接标题", "旧链接简介", None)

        with patch(
            "research.views.website_loader.load_website_metadata",
            side_effect=delayed_metadata,
        ):
            try:
                page.get_by_role("button", name="读取资料信息", exact=True).click()
                self.assertTrue(started.wait(timeout=5))
                page.get_by_label("原始链接:", exact=True).fill(
                    "https://example.com/new"
                )
                release.set()
                expect(
                    page.locator("yuanjian-metadata").get_by_role("status")
                ).to_contain_text("链接已更改")
                expect(page.get_by_label("资料标题:", exact=True)).to_have_value("")
                expect(page.get_by_label("简要介绍:", exact=True)).to_have_value("")
            finally:
                release.set()
