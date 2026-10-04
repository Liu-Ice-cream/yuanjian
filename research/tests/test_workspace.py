from unittest.mock import patch
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bookmarks.models import Bookmark
from research.forms import MaterialForm
from research.models import ResearchItem, ResearchProject


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class WorkspaceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("researcher")
        cls.other = User.objects.create_user("other-researcher")
        cls.project = ResearchProject.objects.create(
            owner=cls.user, name="我的课题", description="研究检索与推理"
        )
        cls.foreign_project = ResearchProject.objects.create(
            owner=cls.other, name="他人的私密课题"
        )
        cls.bookmark = cls.make_bookmark(
            cls.user, "我的论文", "https://example.com/paper", notes="已有笔记"
        )
        cls.foreign_bookmark = cls.make_bookmark(
            cls.other, "他人的私密资料", "https://example.com/private", shared=True
        )
        cls.card = ResearchItem.objects.create(
            bookmark=cls.bookmark,
            project=cls.project,
            material_type="paper",
            reading_stage="reviewed",
            conclusion="可检索的结论",
            evidence="表 2 的实验结果",
        )
        ResearchItem.objects.create(
            bookmark=cls.foreign_bookmark,
            project=cls.foreign_project,
            conclusion="他人的私密结论",
        )

    @staticmethod
    def make_bookmark(user, title, url, **kwargs):
        return Bookmark.objects.create(
            owner=user,
            title=title,
            url=url,
            date_added=timezone.now(),
            date_modified=timezone.now(),
            **kwargs,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def payload(self, **kwargs):
        return {
            "url": "https://example.com/new",
            "title": "新增资料",
            "description": "简要说明",
            "notes": "补充笔记",
            "tags": "检索 论文",
            "project": self.project.pk,
            "material_type": "paper",
            "reading_stage": "reading",
            "question": "研究问题",
            "conclusion": "确认的结论",
            "evidence": "原文表 3",
            "limitations": "尚未验证大规模数据",
            "relevance": "用于综述",
            **kwargs,
        }

    def export_text(self, **params):
        response = self.client.get(reverse("research:export"), params)
        self.assertEqual(response.status_code, 200)
        return b"".join(response.streaming_content).decode()

    def test_private_pages_require_login(self):
        self.client.logout()
        for name, args in [
            ("index", []),
            ("projects", []),
            ("project_new", []),
            ("material_new", []),
            ("export", []),
            ("material_detail", [self.bookmark.pk]),
            ("material_edit", [self.bookmark.pk]),
            ("project_edit", [self.project.pk]),
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse("research:" + name, args=args))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(urlparse(response.url).path, settings.LOGIN_URL)

    def test_workspace_only_shows_owned_materials_and_projects(self):
        response = self.client.get(reverse("research:index"))
        self.assertContains(response, "我的论文")
        for text in ("他人的私密资料", "他人的私密课题", "他人的私密结论"):
            self.assertNotContains(response, text)

    def test_shared_bookmark_does_not_grant_research_card_access(self):
        for name in ("material_detail", "material_edit"):
            response = self.client.get(
                reverse("research:" + name, args=[self.foreign_bookmark.pk])
            )
            self.assertEqual(response.status_code, 404)

    def test_foreign_material_cannot_be_updated(self):
        response = self.client.post(
            reverse("research:material_edit", args=[self.foreign_bookmark.pk]),
            self.payload(),
        )
        self.assertEqual(response.status_code, 404)
        self.foreign_bookmark.refresh_from_db()
        self.assertEqual(self.foreign_bookmark.title, "他人的私密资料")

    def test_foreign_project_cannot_be_viewed_edited_or_exported(self):
        for method, url in [
            ("get", reverse("research:project_edit", args=[self.foreign_project.pk])),
            ("post", reverse("research:project_edit", args=[self.foreign_project.pk])),
            ("get", reverse("research:index") + f"?project={self.foreign_project.pk}"),
            ("get", reverse("research:export") + f"?project={self.foreign_project.pk}"),
        ]:
            with self.subTest(method=method, url=url):
                response = (
                    self.client.post(url, {"name": "changed"})
                    if method == "post"
                    else self.client.get(url)
                )
                self.assertEqual(response.status_code, 404)

    def test_project_creation_strips_whitespace_and_stores_owner(self):
        response = self.client.post(
            reverse("research:project_new"),
            {"name": "  新课题  ", "description": "研究目标"},
        )
        self.assertEqual(response.status_code, 302)
        project = ResearchProject.objects.get(name="新课题")
        self.assertEqual(project.owner, self.user)

    def test_duplicate_project_name_returns_form_error(self):
        response = self.client.post(
            reverse("research:project_new"), {"name": self.project.name}
        )
        self.assertContains(response, "已有同名课题", status_code=422)

    def test_another_owner_can_use_same_project_name(self):
        response = self.client.post(
            reverse("research:project_new"), {"name": self.foreign_project.name}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            ResearchProject.objects.filter(name=self.foreign_project.name).count(), 2
        )

    def test_blank_project_name_is_rejected(self):
        self.assertEqual(
            self.client.post(
                reverse("research:project_new"), {"name": "   "}
            ).status_code,
            422,
        )

    def test_create_material_saves_card_tags_and_reading_state(self):
        response = self.client.post(reverse("research:material_new"), self.payload())
        self.assertEqual(response.status_code, 302)
        bookmark = Bookmark.objects.get(owner=self.user, url="https://example.com/new")
        self.assertEqual(bookmark.research_item.conclusion, "确认的结论")
        self.assertEqual(bookmark.research_item.project, self.project)
        self.assertEqual(bookmark.research_item.effective_stage, "reading")
        self.assertTrue(bookmark.unread)
        self.assertEqual(bookmark.tag_names, ["检索", "论文"])

    def test_foreign_project_form_submission_creates_nothing(self):
        count = Bookmark.objects.count()
        response = self.client.post(
            reverse("research:material_new"),
            self.payload(project=self.foreign_project.pk),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(Bookmark.objects.count(), count)

    def test_invalid_url_is_rejected(self):
        response = self.client.post(
            reverse("research:material_new"), self.payload(url="javascript:alert(1)")
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Bookmark.objects.filter(url="javascript:alert(1)").exists())

    def test_duplicate_capture_does_not_overwrite_card_or_notes(self):
        response = self.client.post(
            reverse("research:material_new"),
            self.payload(url=self.bookmark.url, conclusion="must not replace"),
        )
        self.assertContains(response, "资料已存在", status_code=422)
        self.card.refresh_from_db()
        self.bookmark.refresh_from_db()
        self.assertEqual(self.card.conclusion, "可检索的结论")
        self.assertEqual(self.bookmark.notes, "已有笔记")

    def test_edit_material_keeps_same_bookmark_and_updates_stage(self):
        response = self.client.post(
            reverse("research:material_edit", args=[self.bookmark.pk]),
            self.payload(
                url=self.bookmark.url, reading_stage="used", notes=self.bookmark.notes
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.bookmark.refresh_from_db()
        self.card.refresh_from_db()
        self.assertFalse(self.bookmark.unread)
        self.assertEqual(self.card.effective_stage, "used")
        self.assertEqual(self.bookmark.notes, "已有笔记")

    def test_existing_bookmark_without_card_can_be_adopted(self):
        bookmark = self.make_bookmark(
            self.user, "旧收藏", "https://example.com/legacy", notes="导入的旧笔记"
        )
        response = self.client.get(
            reverse("research:material_edit", args=[bookmark.pk])
        )
        self.assertContains(response, "导入的旧笔记")
        response = self.client.post(
            reverse("research:material_edit", args=[bookmark.pk]),
            self.payload(url=bookmark.url, notes=bookmark.notes),
        )
        self.assertEqual(response.status_code, 302)
        bookmark.refresh_from_db()
        self.assertEqual(bookmark.notes, "导入的旧笔记")
        self.assertEqual(bookmark.research_item.project, self.project)

    def test_card_validation_failure_rolls_back_bookmark_and_tags(self):
        form = MaterialForm(self.user, self.payload())
        self.assertTrue(form.is_valid())
        with (
            patch.object(
                ResearchItem, "full_clean", side_effect=ValidationError("failure")
            ),
            self.assertRaises(ValidationError),
        ):
            form.save()
        self.assertFalse(
            Bookmark.objects.filter(url="https://example.com/new").exists()
        )
        self.assertFalse(self.user.tag_set.filter(name="检索").exists())

    def test_search_matches_card_content(self):
        response = self.client.get(reverse("research:index"), {"q": "可检索的结论"})
        self.assertContains(response, "我的论文")

    def test_multiple_matching_tags_do_not_duplicate_search_results(self):
        self.client.post(
            reverse("research:material_new"), self.payload(tags="match-one match-two")
        )
        response = self.client.get(reverse("research:index"), {"q": "match"})
        self.assertEqual(response.context["page"].paginator.count, 1)

    def test_filters_and_export_use_same_owned_subset(self):
        self.client.post(
            reverse("research:material_new"),
            self.payload(material_type="code", reading_stage="reading"),
        )
        params = {
            "project": self.project.pk,
            "type": "paper",
            "stage": "reviewed",
            "q": "可检索",
        }
        response = self.client.get(reverse("research:index"), params)
        self.assertEqual(response.context["page"].paginator.count, 1)
        text = self.export_text(**params)
        self.assertIn("我的论文", text)
        self.assertIn("可检索的结论", text)
        self.assertNotIn("新增资料", text)
        self.assertNotIn("他人的", text)

    def test_legacy_read_state_changes_remain_consistent_with_filters(self):
        self.bookmark.unread = True
        self.bookmark.save()
        response = self.client.get(reverse("research:index"), {"stage": "collected"})
        self.assertContains(response, "我的论文")
        self.assertEqual(response.context["page"].object_list[0].stage, "collected")
        self.assertNotIn("我的论文", self.export_text(stage="reviewed"))

    def test_reading_stage_and_used_stage_filters(self):
        for stage in ResearchItem.ReadingStage.values:
            self.client.post(
                reverse("research:material_edit", args=[self.bookmark.pk]),
                self.payload(url=self.bookmark.url, reading_stage=stage),
            )
            with self.subTest(stage=stage):
                response = self.client.get(reverse("research:index"), {"stage": stage})
                self.assertContains(response, "新增资料")
                self.assertEqual(response.context["page"].paginator.count, 1)

    def test_unclassified_and_unassigned_filters_include_legacy_bookmarks(self):
        self.make_bookmark(self.user, "未整理收藏", "https://example.com/unclassified")
        response = self.client.get(
            reverse("research:index"), {"type": "unclassified", "project": "unassigned"}
        )
        self.assertContains(response, "未整理收藏")
        self.assertNotContains(response, "我的论文")

    def test_export_contains_all_pages_and_original_sources(self):
        for i in range(25):
            bookmark = self.make_bookmark(
                self.user, f"资料 {i}", f"https://example.com/export-{i}"
            )
            ResearchItem.objects.create(bookmark=bookmark, project=self.project)
        response = self.client.get(
            reverse("research:index"), {"project": self.project.pk}
        )
        self.assertEqual(len(response.context["page"]), 24)
        text = self.export_text(project=self.project.pk)
        for i in range(25):
            self.assertIn(f"https://example.com/export-{i}", text)
        self.assertIn(self.bookmark.url, text)

    def test_export_escapes_html_and_markdown_title_injection(self):
        self.bookmark.title = "[危险标题] <script>bad</script>\n# second heading"
        self.bookmark.url = "https://example.com/a)b"
        self.bookmark.save()
        text = self.export_text()
        self.assertNotIn("<script>", text)
        self.assertIn("\\[危险标题\\]", text)
        self.assertIn("a%29b", text)

    def test_malformed_filters_return_404(self):
        for params in (
            {"project": "not-an-id"},
            {"project": "99999999999999999999999999999999"},
            {"type": "unknown"},
            {"stage": "unknown"},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self.client.get(reverse("research:index"), params).status_code, 404
                )

    def test_project_deletion_preserves_material_and_research_notes(self):
        self.project.delete()
        self.bookmark.refresh_from_db()
        self.card.refresh_from_db()
        self.assertIsNone(self.card.project_id)
        self.assertEqual(self.card.conclusion, "可检索的结论")

    def test_bookmark_deletion_cascades_only_its_card(self):
        self.bookmark.delete()
        self.assertFalse(ResearchItem.objects.filter(pk=self.card.pk).exists())
        self.assertTrue(
            ResearchItem.objects.filter(bookmark=self.foreign_bookmark).exists()
        )

    def test_model_rejects_cross_owner_project_assignment(self):
        self.card.project = self.foreign_project
        with self.assertRaises(ValidationError):
            self.card.full_clean()

    def test_mutating_unsupported_methods_are_rejected(self):
        self.assertEqual(self.client.post(reverse("research:export")).status_code, 405)
        self.assertEqual(
            self.client.delete(
                reverse("research:material_edit", args=[self.bookmark.pk])
            ).status_code,
            405,
        )
