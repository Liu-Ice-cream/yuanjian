from pathlib import Path

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect

from bookmarks.tests_e2e.helpers import LinkdingE2ETestCase
from research.models import (
    ResearchExcerpt,
    ResearchGroup,
    ResearchItem,
    ResearchProject,
)


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class ResearchOutlineE2ETestCase(LinkdingE2ETestCase):
    def setUp(self):
        super().setUp()
        self.project = ResearchProject.objects.create(
            owner=self.get_or_create_test_user(), name="编排流程课题"
        )
        self.bookmark = self.setup_bookmark(
            title="编排来源论文", url="https://example.com/paper"
        )
        ResearchItem.objects.create(bookmark=self.bookmark, project=self.project)
        for text, location in [("第一条证据", "第 1 页"), ("第二条证据", "表 2")]:
            ResearchExcerpt.objects.create(
                bookmark=self.bookmark,
                original_text=text,
                locator=location,
                interpretation="复用理解",
            )

    def board_path(self):
        return reverse("research:outline", args=[self.project.pk])

    def test_create_select_reorder_move_and_download_outline(self):
        page = self.open(reverse("research:index") + f"?project={self.project.pk}")
        page.get_by_role("link", name="编排课题材料", exact=True).click()
        expect(
            page.get_by_role("heading", name="编排流程课题 · 材料编排", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="新建材料分组", exact=True).first.click()
        page.get_by_label("分组名称:", exact=True).fill("背景")
        page.get_by_label("分组说明:", exact=True).fill("整理研究背景")
        page.get_by_role("button", name="保存分组", exact=True).click()
        expect(page.get_by_role("heading", name="背景", exact=True)).to_be_visible()
        page.get_by_role("button", name="加入分组", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("请先勾选需要加入分组的摘录")
        for text in ["第一条证据", "第二条证据"]:
            page.get_by_role("checkbox", name="选择摘录：" + text, exact=True).check()
        page.get_by_role("button", name="加入分组", exact=True).click()
        expect(page.locator("#placed-excerpts article")).to_have_count(2)
        page.locator("#placed-excerpts article").filter(
            has_text="第二条证据"
        ).get_by_role("button", name="上移材料", exact=True).click()
        expect(page.locator("#placed-excerpts article").first).to_contain_text(
            "第二条证据"
        )
        page.get_by_role("link", name="返回材料编排", exact=True).click()
        page.get_by_role("link", name="新建材料分组", exact=True).click()
        page.get_by_label("分组名称:", exact=True).fill("实验依据")
        page.get_by_role("button", name="保存分组", exact=True).click()
        expect(page.get_by_role("heading", name="实验依据", exact=True)).to_be_visible()
        page.get_by_role("link", name="返回材料编排", exact=True).click()
        page.locator(".research-outline-group").filter(has_text="实验依据").get_by_role(
            "button", name="上移分组", exact=True
        ).click()
        expect(page.locator(".research-outline-group").first).to_contain_text(
            "实验依据"
        )
        page.get_by_role("link", name="背景", exact=True).click()
        article = page.locator("#placed-excerpts article").filter(has_text="第一条证据")
        target = ResearchGroup.objects.get(project=self.project, name="实验依据")
        article.get_by_role("combobox", name="目标分组").select_option(str(target.pk))
        article.get_by_role("button", name="移到该分组", exact=True).click()
        expect(page.locator("#placed-excerpts article")).to_have_count(1)
        page.get_by_role("link", name="返回材料编排", exact=True).click()
        with page.expect_download() as download_info:
            page.get_by_role("link", name="导出材料提纲", exact=True).click()
        text = Path(download_info.value.path()).read_text(encoding="utf-8")
        self.assertLess(text.index("## 1. 实验依据"), text.index("## 2. 背景"))
        self.assertLess(text.index("第一条证据"), text.index("第二条证据"))
        for value in [self.bookmark.url, "第 1 页", "表 2", "复用理解"]:
            self.assertIn(value, text)

    def test_removed_material_can_be_readded_and_group_restored(self):
        group = ResearchGroup.objects.create(project=self.project, name="方法")
        page = self.open(
            reverse("research:group_detail", args=[self.project.pk, group.pk])
        )
        page.get_by_role("checkbox", name="选择摘录：第一条证据", exact=True).check()
        page.get_by_role("button", name="加入分组", exact=True).click()
        expect(page.locator("#placed-excerpts article")).to_have_count(1)
        page.get_by_role("button", name="移出分组（可重新加入）", exact=True).click()
        expect(page.locator("#placed-excerpts article")).to_have_count(0)
        page.get_by_role("checkbox", name="选择摘录：第一条证据", exact=True).check()
        page.get_by_role("button", name="加入分组", exact=True).click()
        expect(page.locator("#placed-excerpts article")).to_have_count(1)
        page.get_by_role("link", name="返回材料编排", exact=True).click()
        page.get_by_role("button", name="移除分组（可恢复）", exact=True).click()
        expect(page.locator(".research-outline-group")).to_have_count(0)
        page.locator(".research-removed-groups summary").click()
        page.get_by_role("button", name="恢复分组", exact=True).click()
        expect(page.locator(".research-outline-group")).to_have_count(1)
        expect(page.locator(".research-outline-group")).to_contain_text("第一条证据")
