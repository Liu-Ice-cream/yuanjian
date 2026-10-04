import ipaddress
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from bookmarks.models import Bookmark
from bookmarks.services import http_client
from bookmarks.services.http_client import BlockedAddressError
from bookmarks.services.website_loader import WebsiteMetadata
from research.models import ResearchItem, ResearchProject
from research.tests import test_workspace


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class CaptureTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("capture-user")
        cls.other = User.objects.create_user("other-capture-user")
        cls.project = ResearchProject.objects.create(owner=cls.user, name="我的课题")
        cls.foreign = ResearchProject.objects.create(owner=cls.other, name="私密课题")

    def setUp(self):
        self.client.force_login(self.user)

    def test_capture_links_and_form_inherit_owned_project(self):
        response = self.client.get(
            reverse("research:index"), {"project": self.project.pk}
        )
        capture_url = reverse("research:material_new") + f"?project={self.project.pk}"
        self.assertContains(response, f'href="{capture_url}"')
        response = self.client.get(capture_url)
        self.assertEqual(response.context["form"]["project"].value(), self.project.pk)
        self.assertEqual(ResearchItem.objects.count(), 0)

    def test_foreign_and_malformed_prefilled_projects_are_rejected(self):
        for project_id in (self.foreign.pk, "not-an-id", "999999999999999999999999999"):
            with self.subTest(project_id=project_id):
                response = self.client.get(
                    reverse("research:material_new"), {"project": project_id}
                )
                self.assertEqual(response.status_code, 404)

    def test_prefill_is_optional_and_user_can_change_it_when_saving(self):
        response = self.client.get(reverse("research:material_new"))
        self.assertIsNone(response.context["form"]["project"].value())
        response = self.client.post(
            reverse("research:material_new") + f"?project={self.project.pk}",
            {
                "url": "https://example.com/without-project",
                "material_type": "other",
                "reading_stage": "collected",
                "project": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(ResearchItem.objects.get().project_id)

    def test_metadata_requires_login_and_post(self):
        url = reverse("research:metadata")
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        with patch("research.views.website_loader.load_website_metadata") as loader:
            self.assertEqual(
                self.client.post(url, {"url": "https://example.com"}).status_code, 302
            )
            loader.assert_not_called()

    def test_metadata_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        with patch("research.views.website_loader.load_website_metadata") as loader:
            self.assertEqual(
                client.post(
                    reverse("research:metadata"), {"url": "https://example.com"}
                ).status_code,
                403,
            )
            loader.assert_not_called()

    def test_metadata_reads_without_saving_or_replacing_existing_notes(self):
        bookmark = test_workspace.WorkspaceTestCase.make_bookmark(
            self.user, "手工标题", "https://example.com", notes="原研究笔记"
        )
        metadata = WebsiteMetadata(bookmark.url, "网站标题", "网页简介", None)
        with patch(
            "research.views.website_loader.load_website_metadata", return_value=metadata
        ) as loader:
            response = self.client.post(
                reverse("research:metadata"), {"url": bookmark.url}
            )
        loader.assert_called_once_with(bookmark.url, trust_env=False)
        self.assertTrue(response.json()["available"])
        self.assertEqual(response.json()["title"], "网站标题")
        self.assertEqual(response.json()["description"], "网页简介")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(Bookmark.objects.count(), 1)
        self.assertEqual(ResearchItem.objects.count(), 0)
        bookmark.refresh_from_db()
        self.assertEqual(bookmark.title, "手工标题")
        self.assertEqual(bookmark.notes, "原研究笔记")

    def test_invalid_schemes_and_urls_never_reach_loader(self):
        with patch("research.views.website_loader.load_website_metadata") as loader:
            for url in (
                "",
                "javascript:alert(1)",
                "file:///etc/passwd",
                "ftp://example.com/a",
                "invalid",
                "https://example.com/" + "a" * 2048,
            ):
                with self.subTest(url=url):
                    response = self.client.post(
                        reverse("research:metadata"), {"url": url}
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertFalse(response.json()["available"])
            loader.assert_not_called()

    def test_empty_metadata_allows_manual_save(self):
        with patch(
            "research.views.website_loader.load_website_metadata",
            return_value=WebsiteMetadata("https://example.com", None, None, None),
        ):
            response = self.client.post(
                reverse("research:metadata"), {"url": "https://example.com"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])
        self.assertIn("仍可以", response.json()["message"])
        response = self.client.post(
            reverse("research:material_new"),
            {
                "url": "https://example.com",
                "title": "手工保存",
                "material_type": "other",
                "reading_stage": "collected",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Bookmark.objects.filter(title="手工保存").exists())

    def test_guarded_loader_keeps_empty_result_after_blocking_private_address(self):
        # Exercise the real parser/loader path, including its graceful failure.
        error = BlockedAddressError("127.0.0.1", ipaddress.ip_address("127.0.0.1"))
        with patch("bookmarks.services.http_client.get", side_effect=error) as get:
            response = self.client.post(
                reverse("research:metadata"), {"url": "http://127.0.0.1/"}
            )
        self.assertFalse(response.json()["available"])
        self.assertFalse(get.call_args.kwargs["trust_env"])

    def test_http_error_page_is_not_used_as_metadata(self):
        with patch("bookmarks.services.http_client.get") as get:
            response = get.return_value.__enter__.return_value
            response.raise_for_status.side_effect = http_client.RequestException(
                "HTTP 404"
            )
            result = self.client.post(
                reverse("research:metadata"), {"url": "https://example.com/missing"}
            )
        self.assertFalse(result.json()["available"])
        response.iter_content.assert_not_called()


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class OrganizationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("organizer")
        cls.other = User.objects.create_user("other-organizer")
        cls.project = ResearchProject.objects.create(owner=cls.user, name="整理课题")
        cls.legacy = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.user, "旧收藏", "https://example.com/legacy", notes="旧笔记仍保留"
        )
        cls.blank = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.user, "空卡片", "https://example.com/blank", unread=True
        )
        ResearchItem.objects.create(
            bookmark=cls.blank,
            project=cls.project,
            question=" \t\n",
            conclusion="  ",
            evidence="只有证据",
        )
        for name, field in (("只记录问题", "question"), ("只记录结论", "conclusion")):
            bookmark = test_workspace.WorkspaceTestCase.make_bookmark(
                cls.user, name, "https://example.com/" + field
            )
            ResearchItem.objects.create(
                bookmark=bookmark, project=cls.project, **{field: "有效研究记录"}
            )
        archived = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.user, "已归档待整理", "https://example.com/archived", is_archived=True
        )
        ResearchItem.objects.create(bookmark=archived)
        foreign = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.other, "他人的待整理", "https://example.com/foreign", shared=True
        )
        ResearchItem.objects.create(bookmark=foreign)

    def setUp(self):
        self.client.force_login(self.user)

    def test_stats_do_not_count_blank_cards_or_old_notes_as_research_records(self):
        response = self.client.get(reverse("research:index"))
        self.assertEqual(response.context["total_count"], 4)
        self.assertEqual(response.context["pending_count"], 2)
        self.assertEqual(response.context["record_count"], 2)
        self.assertFalse(self.blank.research_item.has_research_record)

    def test_pending_and_recorded_filters_follow_same_definition(self):
        pending = self.client.get(
            reverse("research:index"), {"organization": "pending"}
        )
        self.assertEqual(
            {material.title for material in pending.context["page"]},
            {"旧收藏", "空卡片"},
        )
        self.assertNotContains(pending, "他人的待整理")
        recorded = self.client.get(
            reverse("research:index"), {"organization": "recorded"}
        )
        self.assertEqual(
            {material.title for material in recorded.context["page"]},
            {"只记录问题", "只记录结论"},
        )

    def test_project_search_stage_and_export_keep_pending_scope(self):
        params = {
            "organization": "pending",
            "project": self.project.pk,
            "stage": "collected",
            "q": "空卡片",
        }
        response = self.client.get(reverse("research:index"), params)
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertIn("organization=pending", response.context["export_url"])
        response = self.client.get(reverse("research:export"), params)
        exported = b"".join(response.streaming_content).decode()
        self.assertIn("https://example.com/blank", exported)
        self.assertNotIn("https://example.com/legacy", exported)
        self.assertNotIn("https://example.com/conclusion", exported)

    def test_organization_tabs_preserve_filters_and_remove_old_page_number(self):
        response = self.client.get(
            reverse("research:index"),
            {"project": self.project.pk, "q": "资料", "stage": "reading", "page": 2},
        )
        pending_url = response.context["organization_urls"]["pending"]
        self.assertIn("organization=pending", pending_url)
        self.assertIn(f"project={self.project.pk}", pending_url)
        self.assertIn("stage=reading", pending_url)
        self.assertNotIn("page=", pending_url)

    def test_filling_question_moves_existing_material_out_of_pending(self):
        response = self.client.post(
            reverse("research:material_edit", args=[self.legacy.pk]),
            {
                "url": self.legacy.url,
                "title": self.legacy.title,
                "notes": self.legacy.notes,
                "question": "用于解决什么问题",
                "material_type": "article",
                "reading_stage": "reading",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.notes, "旧笔记仍保留")
        pending = self.client.get(
            reverse("research:index"), {"organization": "pending"}
        )
        self.assertNotContains(pending, self.legacy.title)
        self.assertEqual(pending.context["record_count"], 3)

    def test_archived_scope_and_invalid_organization(self):
        response = self.client.get(
            reverse("research:index"), {"organization": "pending", "archived": "on"}
        )
        self.assertContains(response, "已归档待整理")
        self.assertNotContains(response, "旧收藏")
        self.assertEqual(
            self.client.get(
                reverse("research:index"), {"organization": "unknown"}
            ).status_code,
            404,
        )
