import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from research.models import (
    ResearchExcerpt,
    ResearchGroup,
    ResearchItem,
    ResearchPaper,
    ResearchPlacement,
    ResearchProject,
)
from research.paper_forms import PREVIEW_SALT
from research.paper_services import (
    export_bibtex,
    lookup_crossref,
    normalize_doi,
    parse_crossref,
)
from research.tests import test_workspace


@override_settings(LD_DISABLE_BACKGROUND_TASKS=True, LD_ENABLE_SNAPSHOTS=False)
class ResearchPaperTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("paper-owner")
        cls.other = User.objects.create_user("paper-other")
        cls.project = ResearchProject.objects.create(owner=cls.user, name="引用课题")
        cls.foreign_project = ResearchProject.objects.create(
            owner=cls.other, name="秘密课题"
        )
        cls.bookmark = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.user, "原资料标题", "https://example.com/paper", notes="原笔记"
        )
        cls.item = ResearchItem.objects.create(
            bookmark=cls.bookmark,
            project=cls.project,
            material_type="paper",
            question="原研究问题",
        )
        cls.foreign = test_workspace.WorkspaceTestCase.make_bookmark(
            cls.other, "公开分享收藏", "https://example.com/private", shared=True
        )
        ResearchItem.objects.create(
            bookmark=cls.foreign, project=cls.foreign_project, material_type="paper"
        )
        cls.meta = {
            "doi": "10.1038/nature14539",
            "title": "Deep learning",
            "authors": "LeCun, Yann\nBengio, Yoshua\nHinton, Geoffrey",
            "year": "2015",
            "venue": "Nature",
            "entry_type": "article",
        }

    def setUp(self):
        self.client.force_login(self.user)

    def paper_url(self, bookmark=None):
        return reverse("research:paper_edit", args=[(bookmark or self.bookmark).pk])

    def citation_url(self, name="citations", project=None, scope=None):
        url = reverse("research:" + name, args=[(project or self.project).pk])
        return url + ("?scope=" + scope if scope else "")

    def payload(self, **overrides):
        return {
            "doi": self.meta["doi"],
            "title": "",
            "authors": "",
            "year": "",
            "venue": "",
            "entry_type": "misc",
            "action": "save",
            **overrides,
        }

    def token(self, owner=None, bookmark=None, metadata=None):
        return signing.dumps(
            {
                "owner": (owner or self.user).pk,
                "bookmark": (bookmark or self.bookmark).pk,
                "metadata": metadata or self.meta,
            },
            salt=PREVIEW_SALT,
        )

    def download(self, scope="project"):
        response = self.client.get(self.citation_url("citations_export", scope=scope))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn(".bib", response["Content-Disposition"])
        return b"".join(response.streaming_content).decode()

    def test_doi_normalization_accepts_urls_prefixes_case_and_encoded_slash(self):
        for doi in [
            " 10.1038/NATURE14539 ",
            "doi:10.1038/NATURE14539",
            "https://doi.org/10.1038%2Fnature14539?utm_source=test",
            "http://dx.doi.org/10.1038/nature14539",
        ]:
            self.assertEqual(normalize_doi(doi), self.meta["doi"])

    def test_invalid_doi_rejected_before_network(self):
        with patch("research.paper_views.lookup_crossref") as lookup:
            for doi in [
                "http://127.0.0.1/10.1038/test",
                "https://[",
                "https://doi.org@evil.example/10.1038/test",
                "https://doi.org:443/10.1038/test",
                "https://api.crossref.org/works/10.1038/test",
                "10.1038/space here",
                "10.1038/<script>",
                "10.12/short",
            ]:
                with self.subTest(doi=doi):
                    response = self.client.post(
                        self.paper_url(), self.payload(action="lookup", doi=doi)
                    )
                    self.assertEqual(response.status_code, 422)
            lookup.assert_not_called()
        self.assertEqual(ResearchPaper.objects.count(), 0)

    def test_preview_does_not_write_and_preserves_current_fields(self):
        with patch("research.paper_views.lookup_crossref", return_value=self.meta):
            response = self.client.post(
                self.paper_url(),
                self.payload(
                    action="lookup", title="手工修订", authors="自填作者", year="2020"
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["candidate"]["title"], "Deep learning")
        self.assertEqual(response.context["form"]["title"].value(), "手工修订")
        self.assertEqual(response.context["form"]["authors"].value(), "自填作者")
        self.assertEqual(ResearchPaper.objects.count(), 0)

    def test_apply_fills_blanks_without_overwriting_manual_fields(self):
        response = self.client.post(
            self.paper_url(),
            self.payload(
                action="apply",
                lookup_token=self.token(),
                title="手工标题",
                year="2021",
                entry_type="inproceedings",
            ),
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form["title"].value(), "手工标题")
        self.assertEqual(form["year"].value(), "2021")
        self.assertEqual(form["entry_type"].value(), "inproceedings")
        self.assertEqual(form["authors"].value(), self.meta["authors"])
        self.assertEqual(form["venue"].value(), "Nature")
        self.assertEqual(ResearchPaper.objects.count(), 0)

    def test_save_imported_information_and_manual_correction_preserves_source_data(
        self,
    ):
        response = self.client.post(
            self.paper_url(), self.payload(**self.meta, lookup_token=self.token())
        )
        self.assertEqual(response.status_code, 302)
        paper = ResearchPaper.objects.get(bookmark=self.bookmark)
        self.assertEqual(paper.fetched_doi, self.meta["doi"])
        self.assertIsNotNone(paper.fetched_at)
        self.client.post(
            self.paper_url(), self.payload(**{**self.meta, "title": "人工修正标题"})
        )
        paper.refresh_from_db()
        self.assertEqual(paper.title, "人工修正标题")
        self.bookmark.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.bookmark.title, "原资料标题")
        self.assertEqual(self.bookmark.notes, "原笔记")
        self.assertEqual(self.item.question, "原研究问题")

    def test_refresh_only_offers_preview_and_leaves_saved_corrections_unchanged(self):
        ResearchPaper.objects.create(
            bookmark=self.bookmark,
            owner=self.user,
            doi=self.meta["doi"],
            title="人工标题",
            authors="人工作者",
            year=2022,
        )
        with patch("research.paper_views.lookup_crossref", return_value=self.meta):
            response = self.client.post(
                self.paper_url(),
                self.payload(
                    action="lookup", title="人工标题", authors="人工作者", year="2022"
                ),
            )
        self.assertEqual(response.context["form"]["title"].value(), "人工标题")
        self.assertEqual(
            ResearchPaper.objects.get(bookmark=self.bookmark).title, "人工标题"
        )

    def test_lookup_failure_keeps_manual_content_and_allows_save(self):
        with patch("research.paper_views.lookup_crossref", return_value=None):
            response = self.client.post(
                self.paper_url(),
                self.payload(action="lookup", title="手工保留", authors="作者"),
            )
        self.assertContains(response, "仍可手动保存")
        self.assertEqual(response.context["form"]["title"].value(), "手工保留")
        self.assertEqual(
            self.client.post(
                self.paper_url(), self.payload(title="手工保留", authors="作者")
            ).status_code,
            302,
        )

    def test_manual_information_without_doi_is_supported(self):
        self.assertEqual(
            self.client.post(
                self.paper_url(),
                self.payload(doi="", title="无 DOI 的预印本", authors="作者"),
            ).status_code,
            302,
        )
        self.assertIn("无 DOI 的预印本", self.download())

    def test_doi_change_clears_old_lookup_provenance(self):
        ResearchPaper.objects.create(
            bookmark=self.bookmark,
            owner=self.user,
            doi=self.meta["doi"],
            fetched_doi=self.meta["doi"],
            title="旧信息",
        )
        self.client.post(
            self.paper_url(), self.payload(doi="10.1234/changed", title="新信息")
        )
        paper = ResearchPaper.objects.get(bookmark=self.bookmark)
        self.assertEqual(paper.fetched_doi, "")
        self.assertIsNone(paper.fetched_at)

    def test_tampered_cross_user_cross_source_and_changed_doi_tokens_rejected(self):
        for token, doi in [
            ("tampered", self.meta["doi"]),
            (self.token(owner=self.other), self.meta["doi"]),
            (self.token(bookmark=self.foreign), self.meta["doi"]),
            (self.token(), "10.1234/changed"),
        ]:
            for action in ["apply", "save"]:
                with self.subTest(action=action, doi=doi):
                    response = self.client.post(
                        self.paper_url(),
                        self.payload(
                            action=action, doi=doi, lookup_token=token, title="保留输入"
                        ),
                    )
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(
                        response.context["form"]["title"].value(), "保留输入"
                    )
        self.assertEqual(ResearchPaper.objects.count(), 0)

    def test_expired_preview_is_rejected(self):
        with patch("django.core.signing.time.time", return_value=1):
            token = self.token()
        self.assertEqual(
            self.client.post(
                self.paper_url(), self.payload(action="apply", lookup_token=token)
            ).status_code,
            422,
        )

    def test_discard_token_retains_fields_and_can_save_manually(self):
        response = self.client.post(
            self.paper_url(),
            self.payload(action="discard", lookup_token="tampered", title="保留输入"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["lookup_token"].value(), "")
        self.assertEqual(response.context["form"]["title"].value(), "保留输入")

    def test_duplicate_doi_is_blocked_and_links_existing_including_archive(self):
        existing = test_workspace.WorkspaceTestCase.make_bookmark(
            self.user, "已归档论文", "https://example.com/existing", is_archived=True
        )
        ResearchPaper.objects.create(
            bookmark=existing, owner=self.user, doi=self.meta["doi"], title="已有论文"
        )
        for action in ["lookup", "save"]:
            response = self.client.post(
                self.paper_url(), self.payload(action=action, title="输入保留")
            )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.context["duplicate_bookmark"].pk, existing.pk)
        self.assertFalse(ResearchPaper.objects.filter(bookmark=self.bookmark).exists())

    def test_same_doi_is_allowed_for_another_owner(self):
        ResearchPaper.objects.create(
            bookmark=self.foreign,
            owner=self.other,
            doi=self.meta["doi"],
            title="秘密论文",
        )
        self.assertEqual(
            self.client.post(self.paper_url(), self.payload(**self.meta)).status_code,
            302,
        )
        self.assertNotIn("秘密论文", self.download())

    def test_doi_constraint_rejects_racing_duplicate_records(self):
        ResearchPaper.objects.create(
            bookmark=self.bookmark, owner=self.user, doi=self.meta["doi"]
        )
        other = test_workspace.WorkspaceTestCase.make_bookmark(
            self.user, "另一个", "https://example.com/another"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchPaper.objects.create(
                bookmark=other, owner=self.user, doi=self.meta["doi"]
            )

    def test_multiple_records_without_doi_are_allowed(self):
        ResearchPaper.objects.create(bookmark=self.bookmark, owner=self.user, doi="")
        other = test_workspace.WorkspaceTestCase.make_bookmark(
            self.user, "另一个", "https://example.com/another"
        )
        ResearchPaper.objects.create(bookmark=other, owner=self.user, doi="")
        self.assertEqual(ResearchPaper.objects.count(), 2)

    def test_capture_doi_duplicate_is_blocked_before_creating_bookmark(self):
        ResearchPaper.objects.create(
            bookmark=self.bookmark, owner=self.user, doi=self.meta["doi"]
        )
        response = self.client.post(
            reverse("research:material_new"),
            {
                "url": "https://example.com/new",
                "title": "重复论文",
                "doi": "https://doi.org/10.1038/NATURE14539",
                "material_type": "paper",
                "reading_stage": "collected",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context["duplicate_bookmark"].pk, self.bookmark.pk)
        self.assertFalse(
            type(self.bookmark).objects.filter(url="https://example.com/new").exists()
        )

    def test_capture_new_doi_redirects_to_paper_information(self):
        response = self.client.post(
            reverse("research:material_new"),
            {
                "url": "https://example.com/new",
                "title": "新论文",
                "doi": self.meta["doi"],
                "material_type": "paper",
                "reading_stage": "collected",
            },
        )
        self.assertEqual(response.status_code, 302)
        saved = ResearchPaper.objects.get(owner=self.user)
        self.assertEqual(response.url, self.paper_url(saved.bookmark))
        self.assertEqual(saved.title, "")

    def test_foreign_shared_material_and_projects_are_private(self):
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(self.paper_url(self.foreign)).status_code, 404)
        for name in ["citations", "citations_export"]:
            self.assertEqual(
                self.client.get(
                    self.citation_url(name, project=self.foreign_project)
                ).status_code,
                404,
            )

    def test_login_csrf_and_safe_methods(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(
            client.post(self.paper_url(), self.payload(action="lookup")).status_code,
            403,
        )
        self.assertEqual(client.post(self.paper_url(), self.payload()).status_code, 403)
        self.assertEqual(
            self.client.post(self.citation_url("citations_export")).status_code, 405
        )
        self.client.logout()
        for url in [
            self.paper_url(),
            self.citation_url(),
            self.citation_url("citations_export"),
        ]:
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_year_and_text_limits_are_validated_without_losing_input(self):
        for field, value in [
            ("year", "0"),
            ("year", "10000"),
            ("year", "unknown"),
            ("title", "x" * 1001),
            ("authors", "x" * 20001),
            ("venue", "x" * 1001),
        ]:
            response = self.client.post(
                self.paper_url(), self.payload(**{field: value})
            )
            self.assertEqual(response.status_code, 422)
        self.assertEqual(ResearchPaper.objects.count(), 0)

    def test_missing_information_has_warning_and_is_not_fabricated(self):
        ResearchPaper.objects.create(
            bookmark=self.bookmark,
            owner=self.user,
            title="不完整论文",
            doi="10.1234/incomplete",
        )
        response = self.client.get(self.citation_url())
        self.assertContains(response, "缺少 作者、出版年份")
        text = self.download()
        self.assertNotIn("author =", text)
        self.assertNotIn("year =", text)
        self.assertIn("源笺提示：缺少作者、出版年份", text)

    def test_missing_title_and_unrecorded_papers_are_not_exported(self):
        self.assertContains(self.client.get(self.citation_url()), "尚未记录论文信息")
        ResearchPaper.objects.create(
            bookmark=self.bookmark, owner=self.user, authors="某作者", year=2024
        )
        response = self.client.get(self.citation_url())
        self.assertContains(response, "暂不导出")
        self.assertNotContains(response, "下载 BibTeX")
        self.assertNotIn("@misc", self.download())

    def test_outline_exports_each_paper_once_and_excludes_inactive_references(self):
        ResearchPaper.objects.create(
            bookmark=self.bookmark, owner=self.user, **{**self.meta, "year": 2015}
        )
        quote = ResearchExcerpt.objects.create(
            bookmark=self.bookmark, original_text="有效证据", locator="第一页"
        )
        groups = [
            ResearchGroup.objects.create(project=self.project, name=name)
            for name in ["背景", "方法"]
        ]
        for group in groups:
            ResearchPlacement.objects.create(group=group, excerpt=quote)
        self.assertEqual(self.download("outline").count("@misc"), 0)
        self.assertEqual(self.download("outline").count("@article"), 1)
        ResearchGroup.objects.filter(pk__in=[g.pk for g in groups]).update(
            is_archived=True
        )
        self.assertNotIn("Deep learning", self.download("outline"))
        self.assertIn("Deep learning", self.download())

    def test_archived_and_reassigned_sources_excluded_from_exports(self):
        ResearchPaper.objects.create(
            bookmark=self.bookmark, owner=self.user, **{**self.meta, "year": 2015}
        )
        self.bookmark.is_archived = True
        self.bookmark.save()
        self.assertNotIn("Deep learning", self.download())
        self.bookmark.is_archived = False
        self.bookmark.save()
        self.item.project = None
        self.item.save()
        self.assertNotIn("Deep learning", self.download())

    def test_unknown_scope_rejected(self):
        self.assertEqual(
            self.client.get(self.citation_url(scope="other")).status_code, 404
        )

    def test_bibtex_escapes_tex_and_preserves_unicode_and_stable_keys(self):
        paper = ResearchPaper(
            bookmark=self.bookmark,
            owner=self.user,
            title=r"中文 {Title} 100% & $ # _ \input{evil}",
            authors="Doe, Jane\nResearch and Development Group",
            year=2024,
            venue="Nature",
            entry_type="article",
        )
        text = "".join(export_bibtex([paper]))
        self.assertIn("中文", text)
        self.assertIn(r"\{Title\}", text)
        self.assertIn(r"100\%", text)
        self.assertNotIn(r"\input{evil}", text)
        self.assertIn("@article{yuanjian" + str(self.bookmark.pk), text)
        self.assertIn(" and {Research and Development Group}", text)

    def test_identifier_fields_keep_url_query_and_doi_underscores(self):
        self.bookmark.url = "https://example.com/a_b?one=1&two=2#part"
        paper = ResearchPaper(
            bookmark=self.bookmark, owner=self.user, title="Title", doi="10.1234/a_b"
        )
        text = "".join(export_bibtex([paper]))
        self.assertIn("doi = {10.1234/a_b}", text)
        self.assertIn("url = {https://example.com/a_b?one=1&two=2#part}", text)

    def test_crossref_parser_handles_html_and_missing_dates_without_creation_year(self):
        data = {
            "DOI": self.meta["doi"],
            "title": ["<i>Deep</i> learning"],
            "container-title": ["Nature"],
            "author": [{"family": "LeCun", "given": "Yann"}],
            "created": {"date-parts": [[2020]]},
            "type": "journal-article",
        }
        result = parse_crossref(data, self.meta["doi"])
        self.assertEqual(result["title"], "Deep learning")
        self.assertEqual(result["year"], "")
        self.assertEqual(result["authors"], "LeCun, Yann")

    def test_crossref_requires_matching_doi_and_real_title(self):
        for data in [
            {"DOI": "10.1234/other", "title": ["Wrong"]},
            {"DOI": self.meta["doi"], "title": []},
        ]:
            with self.assertRaises(ValueError):
                parse_crossref(data, self.meta["doi"])

    def mock_response(self, status=200, payload=None, chunks=None):
        response = MagicMock()
        response.status_code = status
        response.iter_content.return_value = (
            chunks if chunks is not None else [json.dumps(payload).encode()]
        )
        manager = MagicMock()
        manager.__enter__.return_value = response
        return manager

    def test_crossref_client_uses_fixed_guarded_host_and_bounded_response(self):
        payload = {
            "status": "ok",
            "message": {
                "DOI": self.meta["doi"],
                "title": ["Deep learning"],
                "published": {"date-parts": [[2015]]},
            },
        }
        with patch(
            "research.paper_services.http_client.get",
            return_value=self.mock_response(payload=payload),
        ) as get:
            result = lookup_crossref(self.meta["doi"])
        self.assertEqual(result["title"], "Deep learning")
        self.assertEqual(
            get.call_args.args[0],
            "https://api.crossref.org/works/10.1038%2Fnature14539",
        )
        self.assertFalse(get.call_args.kwargs["trust_env"])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertTrue(get.call_args.kwargs["stream"])
        with patch(
            "research.paper_services.http_client.get",
            return_value=self.mock_response(chunks=[b"x" * (1024 * 1024 + 1)]),
        ):
            self.assertIsNone(lookup_crossref(self.meta["doi"]))

    def test_crossref_failure_status_malformed_and_wrong_doi_are_unavailable(self):
        for response in [
            self.mock_response(status=404),
            self.mock_response(status=429),
            self.mock_response(chunks=[b"not-json"]),
            self.mock_response(
                payload={
                    "status": "ok",
                    "message": {"DOI": "10.1234/wrong", "title": ["Wrong"]},
                }
            ),
        ]:
            with patch(
                "research.paper_services.http_client.get", return_value=response
            ):
                self.assertIsNone(lookup_crossref(self.meta["doi"]))

    def test_model_rejects_foreign_owner(self):
        with self.assertRaises(ValidationError):
            ResearchPaper(bookmark=self.foreign, owner=self.user).full_clean()

    def test_ten_papers_can_be_exported_with_complete_information(self):
        for i in range(10):
            bookmark = test_workspace.WorkspaceTestCase.make_bookmark(
                self.user, f"论文{i}", f"https://example.com/paper{i}"
            )
            ResearchItem.objects.create(
                bookmark=bookmark, project=self.project, material_type="paper"
            )
            ResearchPaper.objects.create(
                bookmark=bookmark,
                owner=self.user,
                doi=f"10.1234/paper{i}",
                title=f"论文{i}",
                authors=f"Author{i}, First",
                year=2020 + i % 5,
                venue="Test Journal",
                entry_type="article",
            )
        text = self.download()
        self.assertEqual(text.count("@article"), 10)
        for i in range(10):
            self.assertIn(f"10.1234/paper{i}", text)
            self.assertIn(f"https://example.com/paper{i}", text)
