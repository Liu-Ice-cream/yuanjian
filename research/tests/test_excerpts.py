from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from research.models import ResearchExcerpt, ResearchItem, ResearchProject
from research.tests import test_workspace


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class ResearchExcerptTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("excerpt-owner")
        cls.other = User.objects.create_user("excerpt-other")
        cls.project = ResearchProject.objects.create(owner=cls.user, name="摘录课题")
        cls.other_project = ResearchProject.objects.create(
            owner=cls.other, name="私密课题"
        )
        cls.bookmark = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.user, "论文资料", "https://example.com/paper", notes="原研究笔记"
        )
        ResearchItem.objects.create(bookmark=cls.bookmark, project=cls.project)
        cls.foreign = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.other, "分享的资料", "https://example.com/foreign", shared=True
        )
        ResearchItem.objects.create(bookmark=cls.foreign, project=cls.other_project)
        cls.excerpt = ResearchExcerpt.objects.create(
            bookmark=cls.bookmark,
            original_text="实验使用三个数据集。",
            interpretation="用于设计复现实验。",
            locator="第 5 页，表 2",
        )
        cls.secret = ResearchExcerpt.objects.create(
            bookmark=cls.foreign,
            original_text="私密原文摘录",
            interpretation="私密理解",
            locator="秘密位置",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def payload(self, **overrides):
        return {
            "original_text": "原文内容",
            "interpretation": "我的判断",
            "locator": "第 3 页",
            **overrides,
        }

    def export_text(self, ids, **params):
        path = reverse("research:excerpt_export")
        if params:
            from urllib.parse import urlencode

            path += "?" + urlencode(params)
        response = self.client.post(path, {"selected": ids})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        return b"".join(response.streaming_content).decode()

    def test_excerpt_pages_require_login(self):
        self.client.logout()
        routes = [
            ("excerpts", []),
            ("excerpt_new", [self.bookmark.pk]),
            ("excerpt_edit", [self.bookmark.pk, self.excerpt.pk]),
        ]
        for name, args in routes:
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(reverse("research:" + name, args=args)).status_code,
                    302,
                )
        self.assertEqual(
            self.client.post(
                reverse("research:excerpt_export"), {"selected": [self.excerpt.pk]}
            ).status_code,
            302,
        )

    def test_multiple_excerpts_attach_to_one_source_and_preserve_research_card(self):
        for text in ("第一条新增摘录", "第二条新增摘录"):
            response = self.client.post(
                reverse("research:excerpt_new", args=[self.bookmark.pk]),
                self.payload(original_text=text, bookmark=self.foreign.pk),
            )
            self.assertEqual(response.status_code, 302)
            self.assertIn("#excerpt-", response.url)
        self.assertEqual(
            ResearchExcerpt.objects.filter(bookmark=self.bookmark).count(), 3
        )
        self.bookmark.refresh_from_db()
        self.assertEqual(self.bookmark.notes, "原研究笔记")
        self.assertFalse(self.bookmark.research_item.has_research_record)

    def test_original_text_and_locator_required_interpretation_optional(self):
        path = reverse("research:excerpt_new", args=[self.bookmark.pk])
        before = ResearchExcerpt.objects.count()
        for field in ("original_text", "locator"):
            response = self.client.post(path, self.payload(**{field: " \t\n "}))
            self.assertEqual(response.status_code, 422)
            self.assertIn(field, response.context["form"].errors)
        self.assertEqual(ResearchExcerpt.objects.count(), before)
        self.assertEqual(
            self.client.post(path, self.payload(interpretation="")).status_code, 302
        )

    def test_field_limits_reject_oversized_content_without_saving(self):
        path = reverse("research:excerpt_new", args=[self.bookmark.pk])
        for field, limit in (
            ("original_text", 20000),
            ("interpretation", 20000),
            ("locator", 240),
        ):
            response = self.client.post(
                path, self.payload(**{field: "a" * (limit + 1)})
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn(field, response.context["form"].errors)

    def test_edit_does_not_move_excerpt_to_another_bookmark(self):
        self.client.post(
            reverse("research:excerpt_edit", args=[self.bookmark.pk, self.excerpt.pk]),
            self.payload(bookmark=self.foreign.pk),
        )
        self.excerpt.refresh_from_db()
        self.assertEqual(self.excerpt.bookmark_id, self.bookmark.pk)
        self.assertEqual(self.excerpt.locator, "第 3 页")

    def test_foreign_shared_sources_and_mismatched_parent_are_rejected(self):
        for name, args in (
            ("excerpt_new", [self.foreign.pk]),
            ("excerpt_edit", [self.foreign.pk, self.secret.pk]),
            ("excerpt_edit", [self.bookmark.pk, self.secret.pk]),
            ("excerpt_archive", [self.bookmark.pk, self.secret.pk]),
        ):
            path = reverse("research:" + name, args=args)
            with self.subTest(name=name):
                if name != "excerpt_archive":
                    self.assertEqual(self.client.get(path).status_code, 404)
                self.assertEqual(
                    self.client.post(path, self.payload()).status_code, 404
                )

    def test_csrf_protects_create_edit_archive_and_export(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for name, args in (
            ("excerpt_new", [self.bookmark.pk]),
            ("excerpt_edit", [self.bookmark.pk, self.excerpt.pk]),
            ("excerpt_archive", [self.bookmark.pk, self.excerpt.pk]),
            ("excerpt_export", []),
        ):
            self.assertEqual(
                client.post(
                    reverse("research:" + name, args=args), self.payload()
                ).status_code,
                403,
            )

    def test_archive_and_export_require_post(self):
        for name, args in (
            ("excerpt_archive", [self.bookmark.pk, self.excerpt.pk]),
            ("excerpt_export", []),
        ):
            self.assertEqual(
                self.client.get(reverse("research:" + name, args=args)).status_code, 405
            )

    def test_detail_and_summary_escape_html_and_never_include_foreign_excerpts(self):
        self.excerpt.original_text = '<script>alert("x")</script>'
        self.excerpt.save()
        for path in (
            reverse("research:material_detail", args=[self.bookmark.pk]),
            reverse("research:excerpts"),
        ):
            response = self.client.get(path)
            self.assertNotContains(response, '<script>alert("x")</script>')
            self.assertContains(response, "&lt;script&gt;")
            self.assertNotContains(response, "私密原文摘录")
            self.assertNotContains(response, "私密课题")

    def test_export_contains_selected_content_and_source_without_other_excerpts(self):
        unselected = ResearchExcerpt.objects.create(
            bookmark=self.bookmark, **self.payload(original_text="不要导出的内容")
        )
        text = self.export_text([self.excerpt.pk])
        for expected in (
            self.excerpt.original_text,
            self.excerpt.interpretation,
            self.excerpt.locator,
            self.bookmark.url,
            self.bookmark.title,
            self.project.name,
        ):
            self.assertIn(expected, text)
        self.assertNotIn(unselected.original_text, text)
        self.assertNotIn(self.secret.original_text, text)
        self.assertIn("### 原文摘录", text)
        self.assertIn("### 我的理解", text)

    def test_export_empty_invalid_and_mixed_foreign_selection_returns_no_download(self):
        for ids in (
            [],
            [self.secret.pk],
            [self.excerpt.pk, self.secret.pk],
            ["invalid"],
            ["9" * 100],
        ):
            with self.subTest(ids=ids):
                response = self.client.post(
                    reverse("research:excerpt_export"), {"selected": ids}
                )
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("Content-Disposition", response)
                self.assertNotContains(
                    response, self.secret.original_text, status_code=422
                )

    def test_project_query_and_export_reject_foreign_scope(self):
        for name in ("excerpts", "excerpt_export"):
            path = reverse("research:" + name) + f"?project={self.other_project.pk}"
            response = (
                self.client.post(path, {"selected": [self.excerpt.pk]})
                if name == "excerpt_export"
                else self.client.get(path)
            )
            self.assertEqual(response.status_code, 404)

    def test_search_and_project_scope_remain_in_export_and_pagination(self):
        response = self.client.get(
            reverse("research:excerpts"),
            {"project": self.project.pk, "q": "复现实验", "page": 2},
        )
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertIn(f"project={self.project.pk}", response.context["export_url"])
        self.assertNotIn("page=", response.context["export_url"])
        self.assertIn(
            self.excerpt.original_text,
            self.export_text([self.excerpt.pk], project=self.project.pk, q="复现实验"),
        )
        excluded = self.client.post(
            reverse("research:excerpt_export") + "?q=does-not-match",
            {"selected": [self.excerpt.pk]},
        )
        self.assertEqual(excluded.status_code, 422)

    def test_removal_is_reversible_and_cannot_export_removed_excerpt(self):
        path = reverse(
            "research:excerpt_archive", args=[self.bookmark.pk, self.excerpt.pk]
        )
        self.assertEqual(self.client.post(path).status_code, 302)
        self.excerpt.refresh_from_db()
        self.assertTrue(self.excerpt.is_archived)
        response = self.client.get(reverse("research:excerpts"))
        self.assertNotContains(response, self.excerpt.original_text)
        self.assertEqual(
            self.client.post(
                reverse("research:excerpt_export"), {"selected": [self.excerpt.pk]}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "research:excerpt_edit", args=[self.bookmark.pk, self.excerpt.pk]
                )
            ).status_code,
            404,
        )
        self.client.post(path, {"restore": "on"})
        self.excerpt.refresh_from_db()
        self.assertFalse(self.excerpt.is_archived)
        self.assertEqual(self.excerpt.original_text, "实验使用三个数据集。")
        self.assertContains(
            self.client.get(reverse("research:excerpts")), self.excerpt.original_text
        )

    def test_archived_materials_require_explicit_inclusion(self):
        self.bookmark.is_archived = True
        self.bookmark.save()
        self.assertNotContains(
            self.client.get(reverse("research:excerpts")), self.excerpt.original_text
        )
        self.assertContains(
            self.client.get(reverse("research:excerpts"), {"include_archived": "on"}),
            self.excerpt.original_text,
        )
        self.assertEqual(
            self.client.post(
                reverse("research:excerpt_export"), {"selected": [self.excerpt.pk]}
            ).status_code,
            422,
        )
        self.assertIn(
            self.excerpt.original_text,
            self.export_text([self.excerpt.pk], include_archived="on"),
        )

    def test_legacy_material_without_research_card_supports_excerpts(self):
        bookmark = test_workspace.WorkspaceTestCase.make_bookmark(
            self.user, "旧收藏", "https://example.com/old"
        )
        self.client.post(
            reverse("research:excerpt_new", args=[bookmark.pk]), self.payload()
        )
        excerpt = ResearchExcerpt.objects.get(bookmark=bookmark)
        response = self.client.get(
            reverse("research:excerpts"), {"project": "unassigned"}
        )
        self.assertContains(response, "旧收藏")
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertIn("未归入课题", self.export_text([excerpt.pk]))

    def test_project_membership_follows_source_when_reassigned(self):
        new_project = ResearchProject.objects.create(owner=self.user, name="新的课题")
        ResearchItem.objects.filter(bookmark=self.bookmark).update(project=new_project)
        old = self.client.get(
            reverse("research:excerpts"), {"project": self.project.pk}
        )
        self.assertEqual(old.context["page"].paginator.count, 0)
        new = self.client.get(reverse("research:excerpts"), {"project": new_project.pk})
        self.assertContains(new, self.excerpt.original_text)

    def test_material_search_finds_active_excerpts_without_duplicates(self):
        ResearchExcerpt.objects.create(
            bookmark=self.bookmark, **self.payload(interpretation="用于设计复现实验。")
        )
        response = self.client.get(reverse("research:index"), {"q": "复现实验"})
        self.assertEqual(response.context["page"].paginator.count, 1)
        ResearchExcerpt.objects.filter(bookmark=self.bookmark).update(is_archived=True)
        response = self.client.get(reverse("research:index"), {"q": "复现实验"})
        self.assertEqual(response.context["page"].paginator.count, 0)

    def test_material_export_keeps_active_excerpts(self):
        ResearchExcerpt.objects.create(
            bookmark=self.bookmark,
            **self.payload(original_text="已移除文字"),
            is_archived=True,
        )
        response = self.client.get(
            reverse("research:export"), {"project": self.project.pk}
        )
        text = b"".join(response.streaming_content).decode()
        self.assertIn(self.excerpt.original_text, text)
        self.assertIn(self.excerpt.locator, text)
        self.assertNotIn("已移除文字", text)

    def test_five_materials_ten_excerpts_can_be_selected_for_reuse(self):
        ResearchExcerpt.objects.filter(bookmark__owner=self.user).delete()
        selected = []
        for material_index in range(5):
            bookmark = test_workspace.WorkspaceTestCase.make_bookmark(
                self.user,
                f"验收资料 {material_index}",
                f"https://example.com/acceptance/{material_index}",
            )
            ResearchItem.objects.create(bookmark=bookmark, project=self.project)
            for paragraph in range(2):
                response = self.client.post(
                    reverse("research:excerpt_new", args=[bookmark.pk]),
                    self.payload(
                        original_text=f"原文 {material_index}-{paragraph}",
                        interpretation=f"理解 {material_index}-{paragraph}",
                        locator=f"第 {paragraph + 1} 页",
                    ),
                )
                self.assertEqual(response.status_code, 302)
                if paragraph == 0:
                    selected.append(
                        ResearchExcerpt.objects.filter(bookmark=bookmark)
                        .latest("pk")
                        .pk
                    )
        response = self.client.get(
            reverse("research:excerpts"), {"project": self.project.pk}
        )
        self.assertEqual(response.context["page"].paginator.count, 10)
        text = self.export_text(selected, project=self.project.pk)
        for material_index in range(5):
            self.assertIn(f"原文 {material_index}-0", text)
            self.assertIn(f"理解 {material_index}-0", text)
            self.assertIn(f"https://example.com/acceptance/{material_index}", text)
            self.assertNotIn(f"原文 {material_index}-1", text)

    def test_export_keeps_full_text_and_escapes_markdown_and_html(self):
        self.excerpt.original_text = (
            "长摘录" * 500
            + '\n<script>alert("x")</script>\n![image](https://example.com/x)'
        )
        self.excerpt.interpretation = "我的理解" * 400
        self.excerpt.save()
        text = self.export_text([self.excerpt.pk, self.excerpt.pk])
        self.assertIn("长摘录" * 500, text)
        self.assertIn("我的理解" * 400, text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn(r"\!\[image\]", text)
        self.assertEqual(text.count("### 原文摘录"), 1)

    def test_pagination_keeps_project_search_and_archived_filters(self):
        ResearchExcerpt.objects.bulk_create(
            [
                ResearchExcerpt(
                    bookmark=self.bookmark,
                    **self.payload(original_text=f"分页摘录 {index}"),
                )
                for index in range(26)
            ]
        )
        response = self.client.get(
            reverse("research:excerpts"),
            {
                "project": self.project.pk,
                "q": "分页摘录",
                "include_archived": "on",
                "page": 2,
            },
        )
        self.assertEqual(len(response.context["page"]), 2)
        self.assertIn("include_archived=on", response.context["filter_query"])
        self.assertIn(f"project={self.project.pk}", response.context["filter_query"])
        self.assertNotIn("page=", response.context["filter_query"])
