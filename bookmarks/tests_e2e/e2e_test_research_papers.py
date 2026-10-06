from pathlib import Path
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect

from bookmarks.tests_e2e.helpers import LinkdingE2ETestCase
from research.models import (
    ResearchExcerpt,
    ResearchGroup,
    ResearchItem,
    ResearchPaper,
    ResearchPlacement,
    ResearchProject,
)


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class ResearchPapersE2ETestCase(LinkdingE2ETestCase):
    def setUp(self):
        super().setUp()
        self.project = ResearchProject.objects.create(
            owner=self.get_or_create_test_user(), name="论文引用课题"
        )
        self.meta = {
            "doi": "10.1038/nature14539",
            "title": "Deep learning",
            "authors": "LeCun, Yann\nBengio, Yoshua\nHinton, Geoffrey",
            "year": "2015",
            "venue": "Nature",
            "entry_type": "article",
        }

    def test_capture_lookup_preview_preserves_manual_title_and_downloads_bibtex(self):
        page = self.open(
            reverse("research:material_new") + f"?project={self.project.pk}"
        )
        page.get_by_label("原始链接:", exact=True).fill("https://example.com/paper")
        page.get_by_label("资料标题:", exact=True).fill("论文资料")
        page.get_by_label("论文 DOI（可选）:", exact=True).fill(
            "https://doi.org/10.1038/NATURE14539"
        )
        page.get_by_label("资料类型:", exact=True).select_option("paper")
        page.get_by_role("button", name="保存研究资料", exact=True).click()
        expect(page.get_by_role("heading", name="论文信息", exact=True)).to_be_visible()
        page.get_by_label("论文标题:", exact=True).fill("人工修订标题")
        with patch("research.paper_views.lookup_crossref", return_value=self.meta):
            page.get_by_role("button", name="读取 DOI 信息", exact=True).click()
            expect(
                page.get_by_role("heading", name="候选信息 · Crossref", exact=True)
            ).to_be_visible()
        expect(page.get_by_label("论文标题:", exact=True)).to_have_value("人工修订标题")
        expect(page.get_by_label("作者:", exact=True)).to_have_value("")
        page.get_by_role("button", name="应用到空白字段", exact=True).click()
        expect(page.get_by_label("作者:", exact=True)).to_have_value(
            self.meta["authors"]
        )
        expect(page.get_by_label("出版年份:", exact=True)).to_have_value("2015")
        expect(page.get_by_label("论文标题:", exact=True)).to_have_value("人工修订标题")
        page.get_by_label("引用类型:", exact=True).select_option("article")
        page.get_by_role("button", name="保存论文信息", exact=True).click()
        expect(page.get_by_role("heading", name="论文资料", exact=True)).to_be_visible()
        page.get_by_role("link", name="查看课题论文引用 →", exact=True).click()
        expect(
            page.get_by_role("heading", name="论文引用课题 · 论文引用", exact=True)
        ).to_be_visible()
        with page.expect_download() as download_info:
            page.get_by_role("link", name="下载 BibTeX", exact=True).click()
        text = Path(download_info.value.path()).read_text(encoding="utf-8")
        for expected in [
            "@article",
            "人工修订标题",
            "LeCun, Yann and Bengio, Yoshua and Hinton, Geoffrey",
            "2015",
            "Nature",
            self.meta["doi"],
            "https://example.com/paper",
        ]:
            self.assertIn(expected, text)

    def test_duplicate_capture_links_existing_and_failure_still_allows_manual_save(
        self,
    ):
        bookmark = self.setup_bookmark(
            title="已有论文", url="https://example.com/existing"
        )
        ResearchItem.objects.create(
            bookmark=bookmark, project=self.project, material_type="paper"
        )
        ResearchPaper.objects.create(
            bookmark=bookmark,
            owner=self.get_or_create_test_user(),
            doi=self.meta["doi"],
            title="已保存论文信息",
        )
        page = self.open(reverse("research:material_new"))
        page.get_by_label("原始链接:", exact=True).fill("https://example.com/duplicate")
        page.get_by_label("论文 DOI（可选）:", exact=True).fill(self.meta["doi"])
        page.get_by_role("button", name="保存研究资料", exact=True).click()
        expect(
            page.get_by_text("同一 DOI 的论文已存在，请打开已有资料。", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="打开并编辑原有记录", exact=True).click()
        expect(
            page.get_by_role("heading", name="编辑研究卡片", exact=True)
        ).to_be_visible()
        page.goto(
            self.live_server_url + reverse("research:paper_edit", args=[bookmark.pk])
        )
        page.get_by_label("论文标题:", exact=True).fill("手动保留标题")
        with patch("research.paper_views.lookup_crossref", return_value=None):
            page.get_by_role("button", name="读取 DOI 信息", exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("仍可手动保存")
        expect(page.get_by_label("论文标题:", exact=True)).to_have_value("手动保留标题")
        page.get_by_role("button", name="保存论文信息", exact=True).click()
        expect(page.locator("#paper-info")).to_contain_text("手动保留标题")

    def test_outline_export_deduplicates_sources_and_shows_missing_information(self):
        bookmark = self.setup_bookmark(
            title="提纲论文来源", url="https://example.com/outline-paper"
        )
        ResearchItem.objects.create(
            bookmark=bookmark, project=self.project, material_type="paper"
        )
        ResearchPaper.objects.create(
            bookmark=bookmark,
            owner=self.get_or_create_test_user(),
            title="提纲使用的论文",
            doi="10.1234/outline",
        )
        excerpt = ResearchExcerpt.objects.create(
            bookmark=bookmark, original_text="支持多个论点", locator="第一页"
        )
        for name in ["背景", "方法"]:
            group = ResearchGroup.objects.create(project=self.project, name=name)
            ResearchPlacement.objects.create(group=group, excerpt=excerpt)
        page = self.open(reverse("research:outline", args=[self.project.pk]))
        page.get_by_role("link", name="导出提纲引用", exact=True).click()
        expect(
            page.get_by_role("navigation", name="引用导出范围").get_by_role(
                "link", name="提纲使用的论文", exact=True
            )
        ).to_have_attribute("aria-current", "page")
        expect(page.locator(".research-citation-warnings")).to_contain_text(
            "缺少 作者、出版年份"
        )
        with page.expect_download() as download_info:
            page.get_by_role("link", name="下载 BibTeX", exact=True).click()
        text = Path(download_info.value.path()).read_text(encoding="utf-8")
        self.assertEqual(text.count("@misc"), 1)
        self.assertIn("源笺提示：缺少作者、出版年份", text)
