from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_safe

from bookmarks.models import Bookmark

from .models import ResearchPaper
from .outline_services import available_placements
from .paper_forms import PREVIEW_SALT, PaperForm, read_preview
from .paper_services import export_bibtex, lookup_crossref, normalize_doi
from .views import capture_url, owned_project


@login_required
@require_http_methods(["GET", "POST"])
def edit(request, bookmark_id):
    bookmark = get_object_or_404(Bookmark, pk=bookmark_id, owner=request.user)
    paper = ResearchPaper.objects.filter(bookmark=bookmark, owner=request.user).first()
    data = request.POST.copy() if request.method == "POST" else None
    form = PaperForm(request.user, bookmark, data, instance=paper)
    candidate = None
    notice = ""
    status = 200
    if data is not None:
        action = data.get("action", "save")
        if action in ("lookup", "apply", "discard"):
            try:
                if action == "discard":
                    data["lookup_token"] = ""
                    notice = "已取消候选信息，当前填写内容保留，可手动保存。"
                else:
                    doi = normalize_doi(data.get("doi", ""))
                    if not doi:
                        raise ValidationError("请先填写 DOI 再读取论文信息。")
                    duplicate = (
                        ResearchPaper.objects.filter(owner=request.user, doi=doi)
                        .exclude(bookmark=bookmark)
                        .select_related("bookmark")
                        .first()
                    )
                    if duplicate:
                        form.duplicate = duplicate.bookmark
                        raise ValidationError("同一 DOI 的论文已存在，请打开已有资料。")
                    if action == "lookup":
                        data["lookup_token"] = ""
                        candidate = lookup_crossref(doi)
                        if candidate:
                            data["lookup_token"] = signing.dumps(
                                {
                                    "owner": request.user.pk,
                                    "bookmark": bookmark.pk,
                                    "metadata": candidate,
                                },
                                salt=PREVIEW_SALT,
                                compress=True,
                            )
                            notice = "已读取候选信息。请核对预览，再应用到空白字段。"
                        else:
                            notice = "未能读取 Crossref 信息，可能未收录或服务暂不可用。当前内容保留，仍可手动保存。"
                    else:
                        candidate = read_preview(
                            data.get("lookup_token", ""), request.user, bookmark, doi
                        )
                        for name in ("title", "authors", "year", "venue", "entry_type"):
                            # 'misc' is the default choice, not a blank field.
                            # Never replace a user's chosen citation type.
                            if not data.get(name, "").strip():
                                data[name] = candidate[name]
                        data["doi"] = doi
                        notice = (
                            "已补全空白字段。请核对引用类型及内容，再保存论文信息。"
                        )
                        candidate = None
                duplicate_bookmark = form.duplicate
                form = PaperForm(request.user, bookmark, data, instance=paper)
                form.duplicate = duplicate_bookmark
            except ValidationError as error:
                form.is_valid()
                form.add_error(None, error)
                status = 422
        elif action == "save":
            if form.is_valid():
                saved = form.save(commit=False)
                if form.cleaned_data["lookup_token"]:
                    saved.fetched_doi = form.cleaned_data["doi"]
                    saved.fetched_at = timezone.now()
                elif saved.fetched_doi != saved.doi:
                    saved.fetched_doi = ""
                    saved.fetched_at = None
                try:
                    with transaction.atomic():
                        saved.save()
                    return redirect("research:material_detail", bookmark_id=bookmark.pk)
                except IntegrityError:
                    form.duplicate = (
                        ResearchPaper.objects.filter(owner=request.user, doi=saved.doi)
                        .exclude(bookmark=bookmark)
                        .select_related("bookmark")
                        .first()
                    )
                    if form.duplicate:
                        form.duplicate = form.duplicate.bookmark
                    form.add_error(
                        None, "论文信息已被同时保存，请刷新页面或打开已有资料。"
                    )
            status = 422
        else:
            raise Http404
    item = getattr(bookmark, "research_item", None)
    return render(
        request,
        "research/paper_form.html",
        {
            "page_title": "论文信息 · 源笺",
            "bookmark": bookmark,
            "form": form,
            "candidate": candidate,
            "notice": notice,
            "duplicate_bookmark": form.duplicate,
            "capture_url": capture_url(item.project if item else None),
        },
        status=status,
    )


def citation_context(request, project_id):
    project = owned_project(request.user, project_id)
    scope = request.GET.get("scope", "project")
    if scope not in ("project", "outline"):
        raise Http404
    materials = Bookmark.objects.filter(
        owner=request.user, is_archived=False, research_item__project=project
    )
    if scope == "outline":
        materials = materials.filter(
            pk__in=available_placements(project).values("excerpt__bookmark_id")
        )
    papers = list(
        ResearchPaper.objects.filter(
            owner=request.user, bookmark__in=materials
        ).select_related("bookmark")
    )
    missing = materials.filter(
        research_item__material_type="paper", paper_info__isnull=True
    )
    exportable = [paper for paper in papers if paper.title.strip()]
    warnings = [paper for paper in papers if paper.missing_fields]
    return {
        "page_title": "论文引用 · 源笺",
        "project": project,
        "scope": scope,
        "papers": papers,
        "exportable_count": len(exportable),
        "missing_papers": missing,
        "warnings": warnings,
        "capture_url": capture_url(project),
    }


@login_required
@require_safe
def citations(request, project_id):
    return render(
        request, "research/citations.html", citation_context(request, project_id)
    )


@login_required
@require_safe
def export(request, project_id):
    context = citation_context(request, project_id)
    now = timezone.localtime()
    response = StreamingHttpResponse(
        export_bibtex(context["papers"]),
        content_type="application/x-bibtex; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="yuanjian-{context["scope"]}-{now:%Y-%m-%d}.bib"'
    )
    response["Cache-Control"] = "private, no-store"
    return response
