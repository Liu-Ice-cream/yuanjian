from pathlib import Path

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect

from bookmarks.tests_e2e.helpers import LinkdingE2ETestCase
from research.models import ResearchExcerpt, ResearchItem, ResearchProject


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class ResearchExcerptsE2ETestCase(LinkdingE2ETestCase):
    def setUp(self):
        super().setUp()
        self.bookmark = self.setup_bookmark(
            title="摘录流程资料", url="https://example.com/source"
        )
        self.project = ResearchProject.objects.create(
            owner=self.get_or_create_test_user(), name="摘录流程课题"
        )
        ResearchItem.objects.create(bookmark=self.bookmark, project=self.project)

    def test_multiple_excerpts_edit_and_selected_project_export(self):
        page = self.open(reverse("research:material_detail", args=[self.bookmark.pk]))
        for text, note, location in (
            ("第一段原文", "用于方法对比", "第 2 页"),
            ("第二段原文", "用于实验设计", "表 3"),
        ):
            page.get_by_role("link", name="新增摘录", exact=True).click()
            page.get_by_label("原文摘录:", exact=True).fill(text)
            page.get_by_label("我的理解:", exact=True).fill(note)
            page.get_by_label("来源位置:", exact=True).fill(location)
            page.get_by_role("button", name="保存摘录", exact=True).click()
            expect(
                page.get_by_role("heading", name=self.bookmark.title, exact=True)
            ).to_be_visible()
            expect(page.get_by_text(text, exact=True)).to_be_visible()
        expect(page.locator("#research-excerpts article")).to_have_count(2)
        article = page.locator("#research-excerpts article").filter(
            has_text="第一段原文"
        )
        article.get_by_role("link", name="编辑摘录", exact=True).click()
        expect(page.get_by_label("原文摘录:", exact=True)).to_have_value("第一段原文")
        page.get_by_label("我的理解:", exact=True).fill("更新后的方法对比记录")
        page.get_by_role("button", name="保存摘录", exact=True).click()
        expect(page.get_by_text("更新后的方法对比记录", exact=True)).to_be_visible()
        page.get_by_role("link", name="汇总并导出课题摘录 →", exact=True).click()
        expect(
            page.get_by_role("heading", name="摘录流程课题 · 研究摘录", exact=True)
        ).to_be_visible()
        expect(page.get_by_role("combobox", name="摘录课题筛选")).to_have_value(
            str(self.project.pk)
        )
        page.get_by_role("checkbox", name="选择摘录：第一段原文", exact=True).check()
        with page.expect_download() as download_info:
            page.get_by_role("button", name="导出选中摘录", exact=True).click()
        text = Path(download_info.value.path()).read_text(encoding="utf-8")
        for expected in (
            "第一段原文",
            "更新后的方法对比记录",
            "第 2 页",
            self.bookmark.url,
            self.project.name,
        ):
            self.assertIn(expected, text)
        self.assertNotIn("第二段原文", text)

    def test_removed_excerpt_can_be_restored(self):
        excerpt = ResearchExcerpt.objects.create(
            bookmark=self.bookmark,
            original_text="可恢复的原文",
            interpretation="个人理解",
            locator="第 1 页",
        )
        page = self.open(reverse("research:material_detail", args=[self.bookmark.pk]))
        page.get_by_role("button", name="移除摘录（可恢复）", exact=True).click()
        expect(page.locator("#research-excerpts > article")).to_have_count(0)
        page.locator(".research-removed-excerpts summary").click()
        page.get_by_role("button", name="恢复摘录", exact=True).click()
        expect(
            page.locator(f"#excerpt-{excerpt.pk}").get_by_text(
                "可恢复的原文", exact=True
            )
        ).to_be_visible()
        expect(page.locator(".research-removed-excerpts")).to_have_count(0)

    def test_empty_export_shows_feedback_and_can_be_retried(self):
        ResearchExcerpt.objects.create(
            bookmark=self.bookmark,
            original_text="需要导出的原文",
            locator="Introduction",
        )
        page = self.open(reverse("research:excerpts"))
        page.get_by_role("button", name="导出选中摘录", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("请先勾选需要导出的摘录")
        page.get_by_role(
            "checkbox", name="选择摘录：需要导出的原文", exact=True
        ).check()
        with page.expect_download() as download_info:
            page.get_by_role("button", name="导出选中摘录", exact=True).click()
        text = Path(download_info.value.path()).read_text(encoding="utf-8")
        self.assertIn("需要导出的原文", text)
        self.assertIn("尚未记录。", text)
