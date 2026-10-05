from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from research.models import (
    ResearchExcerpt,
    ResearchGroup,
    ResearchItem,
    ResearchPlacement,
    ResearchProject,
)
from research.tests import test_workspace


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class ResearchOutlineTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("outline-owner")
        cls.other = User.objects.create_user("outline-other")
        cls.project = ResearchProject.objects.create(owner=cls.user, name="研究课题")
        cls.another = ResearchProject.objects.create(owner=cls.user, name="另一课题")
        cls.private = ResearchProject.objects.create(owner=cls.other, name="私密课题")
        cls.bookmark = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.user, "原始论文", "https://example.com/paper", notes="原研究笔记"
        )
        cls.item = ResearchItem.objects.create(
            bookmark=cls.bookmark, project=cls.project, question="原研究问题"
        )
        cls.excerpts = [
            ResearchExcerpt.objects.create(
                bookmark=cls.bookmark,
                original_text=f"证据{i:02d}：实验原文",
                interpretation=f"理解{i:02d}",
                locator=f"第{i}页",
            )
            for i in range(1, 11)
        ]
        foreign = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.other, "公开分享来源", "https://example.com/foreign", shared=True
        )
        ResearchItem.objects.create(bookmark=foreign, project=cls.private)
        cls.secret = ResearchExcerpt.objects.create(
            bookmark=foreign, original_text="秘密证据", locator="秘密页码"
        )
        cls.groups = [
            ResearchGroup.objects.create(project=cls.project, name=name, position=i)
            for i, name in enumerate(["背景", "方法与局限", "实验依据"])
        ]
        cls.foreign_group = ResearchGroup.objects.create(
            project=cls.private, name="秘密分组"
        )

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name, group=None, placement=None, project=None):
        args = [(project or self.project).pk]
        if group:
            args.append(group.pk)
        if placement:
            args.append(placement.pk)
        return reverse("research:" + name, args=args)

    def add(self, group, excerpts):
        response = self.client.post(
            self.url("group_add", group), {"selected": [e.pk for e in excerpts]}
        )
        self.assertEqual(response.status_code, 302)

    def export_text(self):
        response = self.client.get(self.url("outline_export"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("attachment", response["Content-Disposition"])
        return b"".join(response.streaming_content).decode()

    def test_ten_excerpts_in_three_groups_export_order_and_provenance(self):
        for group, excerpts in zip(
            self.groups,
            [self.excerpts[:4], self.excerpts[4:7], self.excerpts[7:]],
            strict=True,
        ):
            self.add(group, excerpts)
        text = self.export_text()
        self.assertEqual(text.count("原文摘录："), 10)
        self.assertLess(text.index("## 1. 背景"), text.index("## 2. 方法与局限"))
        self.assertLess(text.index("## 2. 方法与局限"), text.index("## 3. 实验依据"))
        indexes = [text.index(e.original_text) for e in self.excerpts]
        self.assertEqual(indexes, sorted(indexes))
        for excerpt in self.excerpts:
            self.assertIn(excerpt.locator, text)
            self.assertIn(excerpt.interpretation, text)
        self.assertEqual(text.count(self.bookmark.url), 10)
        self.assertNotIn("秘密", text)
        self.bookmark.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.bookmark.notes, "原研究笔记")
        self.assertEqual(self.item.question, "原研究问题")

    def test_duplicate_add_is_idempotent_and_same_quote_can_support_two_groups(self):
        self.add(self.groups[0], self.excerpts[:2])
        original = list(self.groups[0].placements.values_list("id", "position"))
        self.add(self.groups[0], self.excerpts[:2])
        self.assertEqual(
            original, list(self.groups[0].placements.values_list("id", "position"))
        )
        self.add(self.groups[1], self.excerpts[:1])
        self.assertEqual(ResearchPlacement.objects.count(), 3)
        self.assertEqual(self.export_text().count(self.excerpts[0].original_text), 2)

    def test_group_and_material_reorder_match_export(self):
        self.add(self.groups[0], self.excerpts[:3])
        last = self.groups[0].placements.get(excerpt=self.excerpts[2])
        self.assertEqual(
            self.client.post(
                self.url("placement_order", self.groups[0], last), {"direction": "up"}
            ).status_code,
            302,
        )
        self.assertEqual(
            list(self.groups[0].placements.values_list("excerpt_id", flat=True)),
            [self.excerpts[0].pk, self.excerpts[2].pk, self.excerpts[1].pk],
        )
        self.client.post(self.url("group_order", self.groups[1]), {"direction": "up"})
        text = self.export_text()
        self.assertLess(text.index("## 1. 方法与局限"), text.index("## 2. 背景"))
        self.assertLess(
            text.index(self.excerpts[2].original_text),
            text.index(self.excerpts[1].original_text),
        )

    def test_boundary_and_invalid_order_do_not_change_order(self):
        initial = list(self.project.material_groups.values_list("id", "position"))
        for group, direction in [(self.groups[0], "up"), (self.groups[-1], "down")]:
            self.client.post(self.url("group_order", group), {"direction": direction})
        self.assertEqual(
            initial, list(self.project.material_groups.values_list("id", "position"))
        )
        self.assertEqual(
            self.client.post(
                self.url("group_order", self.groups[0]), {"direction": "sideways"}
            ).status_code,
            400,
        )

    def test_remove_material_and_readd_preserves_original_and_reference(self):
        self.add(self.groups[0], self.excerpts[:2])
        placement = self.groups[0].placements.get(excerpt=self.excerpts[0])
        self.client.post(self.url("placement_remove", self.groups[0], placement))
        self.assertNotIn(self.excerpts[0].original_text, self.export_text())
        self.add(self.groups[0], self.excerpts[:1])
        placement.refresh_from_db()
        self.excerpts[0].refresh_from_db()
        self.assertFalse(placement.is_archived)
        self.assertEqual(self.groups[0].placements.count(), 2)
        self.assertEqual(self.groups[0].placements.last().pk, placement.pk)
        self.assertEqual(self.excerpts[0].original_text, "证据01：实验原文")

    def test_remove_and_restore_group_retains_materials_and_appends(self):
        self.add(self.groups[0], self.excerpts[:1])
        self.client.post(self.url("group_archive", self.groups[0]))
        self.assertNotIn(self.excerpts[0].original_text, self.export_text())
        self.assertContains(self.client.get(self.url("outline")), "恢复分组")
        self.client.post(self.url("group_archive", self.groups[0]), {"restore": "on"})
        self.assertIn(self.excerpts[0].original_text, self.export_text())
        self.assertEqual(self.project.material_groups.last().pk, self.groups[0].pk)

    def test_move_deduplicates_existing_target_reference(self):
        self.add(self.groups[0], self.excerpts[:1])
        self.add(self.groups[1], self.excerpts[:1])
        placement = self.groups[0].placements.get(excerpt=self.excerpts[0])
        self.assertEqual(
            self.client.post(
                self.url("placement_move", self.groups[0], placement),
                {"target": self.groups[1].pk},
            ).status_code,
            302,
        )
        self.assertEqual(self.groups[1].placements.filter(is_archived=False).count(), 1)
        placement.refresh_from_db()
        self.assertTrue(placement.is_archived)
        self.assertEqual(self.export_text().count(self.excerpts[0].original_text), 1)

    def test_live_excerpt_edits_are_reflected_in_outline(self):
        self.add(self.groups[0], self.excerpts[:1])
        ResearchExcerpt.objects.filter(pk=self.excerpts[0].pk).update(
            original_text="更新后的证据", interpretation="更新理解"
        )
        self.assertIn("更新后的证据", self.export_text())
        self.assertIn("更新理解", self.export_text())

    def test_unavailable_sources_are_hidden_without_erasing_references(self):
        self.add(self.groups[0], self.excerpts[:1])
        for reason in ["excerpt", "bookmark", "project"]:
            with self.subTest(reason=reason):
                ResearchExcerpt.objects.filter(pk=self.excerpts[0].pk).update(
                    is_archived=reason == "excerpt"
                )
                type(self.bookmark).objects.filter(pk=self.bookmark.pk).update(
                    is_archived=reason == "bookmark"
                )
                ResearchItem.objects.filter(pk=self.item.pk).update(
                    project=self.another if reason == "project" else self.project
                )
                self.assertNotIn(self.excerpts[0].original_text, self.export_text())
                self.assertContains(
                    self.client.get(self.url("outline")), "1 条暂不可用"
                )
                self.assertContains(
                    self.client.get(self.url("group_detail", self.groups[0])),
                    "1 条材料因",
                )
                self.assertEqual(self.groups[0].placements.count(), 1)
        ResearchItem.objects.filter(pk=self.item.pk).update(project=self.project)
        self.assertIn(self.excerpts[0].original_text, self.export_text())

    def test_mixed_foreign_selection_rejected_entirely(self):
        for bad in [self.secret.pk, "bad", 0, "999999999999999999999999999"]:
            with self.subTest(bad=bad):
                response = self.client.post(
                    self.url("group_add", self.groups[0]),
                    {"selected": [self.excerpts[0].pk, bad]},
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(ResearchPlacement.objects.count(), 0)
                self.assertNotContains(response, "秘密证据", status_code=422)

    def test_other_own_project_excerpt_also_rejected(self):
        ResearchItem.objects.filter(pk=self.item.pk).update(project=self.another)
        response = self.client.post(
            self.url("group_add", self.groups[0]), {"selected": [self.excerpts[0].pk]}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(ResearchPlacement.objects.count(), 0)

    def test_foreign_project_and_group_routes_are_scoped(self):
        for name in ["outline", "outline_export", "group_new"]:
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(self.url(name, project=self.private)).status_code,
                    404,
                )
        for name in [
            "group_detail",
            "group_edit",
            "group_add",
            "group_archive",
            "group_order",
        ]:
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.post(self.url(name, self.foreign_group)).status_code,
                    405 if name == "group_detail" else 404,
                )
        self.assertEqual(
            self.client.get(self.url("group_detail", self.foreign_group)).status_code,
            404,
        )

    def test_move_targets_are_active_and_in_same_project(self):
        self.add(self.groups[0], self.excerpts[:1])
        placement = self.groups[0].placements.first()
        other_group = ResearchGroup.objects.create(
            project=self.another, name="其他课题"
        )
        self.groups[2].is_archived = True
        self.groups[2].save()
        for target in [
            self.foreign_group.pk,
            other_group.pk,
            self.groups[0].pk,
            self.groups[2].pk,
            "999999999999999999999999",
        ]:
            with self.subTest(target=target):
                self.assertEqual(
                    self.client.post(
                        self.url("placement_move", self.groups[0], placement),
                        {"target": target},
                    ).status_code,
                    422,
                )
                placement.refresh_from_db()
                self.assertFalse(placement.is_archived)

    def test_wrong_placement_group_cannot_modify_reference(self):
        self.add(self.groups[0], self.excerpts[:1])
        placement = self.groups[0].placements.first()
        for name in ["placement_order", "placement_remove", "placement_move"]:
            self.assertEqual(
                self.client.post(
                    self.url(name, self.groups[1], placement),
                    {"direction": "up", "target": self.groups[2].pk},
                ).status_code,
                404,
            )
        placement.refresh_from_db()
        self.assertFalse(placement.is_archived)

    def test_group_create_edit_and_duplicate_removed_name(self):
        response = self.client.post(
            self.url("group_new"), {"name": "  文献综述  ", "description": "研究现状"}
        )
        self.assertEqual(response.status_code, 302)
        group = self.project.material_groups.get(name="文献综述")
        self.assertEqual(
            self.client.post(
                self.url("group_edit", group),
                {"name": "研究现状", "description": "修改说明"},
            ).status_code,
            302,
        )
        group.refresh_from_db()
        self.assertEqual(group.description, "修改说明")
        self.client.post(self.url("group_archive", group))
        self.assertEqual(
            self.client.post(self.url("group_new"), {"name": "研究现状"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(self.url("group_new"), {"name": ""}).status_code, 422
        )

    def test_candidate_search_pagination_and_empty_selection_feedback(self):
        ResearchExcerpt.objects.bulk_create(
            [
                ResearchExcerpt(
                    bookmark=self.bookmark, original_text=f"分页证据{i}", locator="附录"
                )
                for i in range(30)
            ]
        )
        response = self.client.get(
            self.url("group_detail", self.groups[0]) + "?q=分页证据&page=2"
        )
        self.assertEqual(len(response.context["page"]), 6)
        self.assertEqual(response.context["filter_q"], "分页证据")
        response = self.client.post(
            self.url("group_add", self.groups[0]) + "?q=分页证据", {}
        )
        self.assertContains(response, "请先勾选需要加入分组的摘录", status_code=422)
        self.assertEqual(response.context["filter_q"], "分页证据")

    def test_selection_cannot_bypass_search_scope(self):
        response = self.client.post(
            self.url("group_add", self.groups[0]) + "?q=证据01",
            {"selected": [self.excerpts[1].pk]},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(ResearchPlacement.objects.count(), 0)

    def test_outline_escapes_markdown_and_keeps_long_original_text(self):
        self.excerpts[0].original_text = (
            "<script>alert(1)</script>\n# 原文 *加粗*\n" + "全文" * 3000
        )
        self.excerpts[0].save()
        self.add(self.groups[0], self.excerpts[:1])
        text = self.export_text()
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("\\# 原文 \\*加粗\\*", text)
        self.assertIn("全文" * 3000, text)

    def test_post_requires_csrf_and_get_cannot_mutate(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for name in ["group_add", "group_archive", "group_order"]:
            self.assertEqual(
                client.post(self.url(name, self.groups[0])).status_code, 403
            )
            self.assertEqual(
                self.client.get(self.url(name, self.groups[0])).status_code, 405
            )
        self.add(self.groups[0], self.excerpts[:1])
        placement = self.groups[0].placements.first()
        for name in ["placement_order", "placement_move", "placement_remove"]:
            self.assertEqual(
                client.post(self.url(name, self.groups[0], placement)).status_code, 403
            )
            self.assertEqual(
                self.client.get(self.url(name, self.groups[0], placement)).status_code,
                405,
            )

    def test_all_entry_points_require_login(self):
        self.add(self.groups[0], self.excerpts[:1])
        placement = self.groups[0].placements.first()
        self.client.logout()
        for name, group, pl in [
            ("outline", None, None),
            ("outline_export", None, None),
            ("group_new", None, None),
            ("group_detail", self.groups[0], None),
            ("group_edit", self.groups[0], None),
            ("group_add", self.groups[0], None),
            ("placement_remove", self.groups[0], placement),
        ]:
            self.assertEqual(
                self.client.get(self.url(name, group, pl)).status_code, 302
            )

    def test_model_validation_rejects_cross_owner_and_cross_project_reference(self):
        for excerpt in [self.secret, self.excerpts[0]]:
            group = (
                self.groups[0]
                if excerpt == self.secret
                else ResearchGroup.objects.create(project=self.another, name="其他")
            )
            with self.assertRaises(ValidationError):
                ResearchPlacement(group=group, excerpt=excerpt).full_clean()

    def test_empty_board_has_guidance_and_no_download_button(self):
        response = self.client.get(self.url("outline", project=self.another))
        self.assertContains(response, "从一个论点或章节开始")
        self.assertNotContains(response, "导出材料提纲")
