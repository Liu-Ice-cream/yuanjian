from pathlib import Path

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect

from bookmarks.tests_e2e.helpers import LinkdingE2ETestCase


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class ResearchWorkspaceE2ETestCase(LinkdingE2ETestCase):
    def test_collect_edit_filter_and_export_research_card(self):
        page = self.open(reverse("research:project_new"))
        page.get_by_label("课题名称:", exact=True).fill("研究流程验证")
        page.get_by_label("研究目标:", exact=True).fill("整理带来源的研究材料")
        page.get_by_role("button", name="保存课题").click()
        expect(page.get_by_role("heading", name="研究流程验证")).to_be_visible()
        page.get_by_role("link", name="收集资料", exact=True).first.click()
        page.get_by_label("原始链接:", exact=True).fill(
            "https://example.com/research-source"
        )
        page.get_by_label("资料标题:", exact=True).fill("示例研究材料")
        page.get_by_label("所属课题:", exact=True).select_option(label="研究流程验证")
        page.get_by_label("资料类型:", exact=True).select_option("paper")
        page.get_by_label("阅读阶段:", exact=True).select_option("reading")
        page.get_by_label("核心结论:", exact=True).fill("结论用于综述材料")
        page.get_by_label("证据与实验:", exact=True).fill("原文表 2")
        page.get_by_role("button", name="保存研究资料").click()
        expect(page.get_by_role("heading", name="示例研究材料")).to_be_visible()
        expect(page.get_by_text("原文表 2", exact=True)).to_be_visible()
        page.get_by_role("link", name="编辑研究卡片", exact=True).click()
        expect(page.get_by_label("核心结论:", exact=True)).to_have_value(
            "结论用于综述材料"
        )
        page.get_by_label("阅读阶段:", exact=True).select_option("used")
        page.get_by_role("button", name="保存研究资料").click()
        expect(page.get_by_text("论文 · 已复用", exact=True)).to_be_visible()
        page.get_by_role("link", name="← 返回研究资料", exact=True).click()
        page.get_by_role("searchbox", name="搜索资料与研究卡片").fill("综述材料")
        page.get_by_role("combobox", name="阅读阶段筛选", exact=True).select_option("used")
        page.get_by_role("button", name="筛选", exact=True).click()
        expect(page.get_by_role("heading", name="示例研究材料")).to_be_visible()
        with page.expect_download() as download_info:
            page.get_by_role("link", name="导出研究材料", exact=True).click()
        text = Path(download_info.value.path()).read_text(encoding="utf-8")
        self.assertIn("https://example.com/research-source", text)
        self.assertIn("结论用于综述材料", text)
        self.assertIn("原文表 2", text)
