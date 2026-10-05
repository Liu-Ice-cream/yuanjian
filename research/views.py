from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
    require_safe,
)

from bookmarks.models import Bookmark
from bookmarks.services import website_loader

from .forms import MaterialForm, MetadataLookupForm, ProjectForm
from .models import ResearchExcerpt, ResearchItem, ResearchProject
from .services import decorate_material, export_markdown, research_record_condition


def capture_url(project=None):
    return reverse("research:material_new") + (
        f"?project={project.pk}" if project else ""
    )


def owned_project(user, project_id):
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        raise Http404 from None
    return get_object_or_404(ResearchProject, pk=project_id, owner=user)


def materials_query(request):
    query = Bookmark.objects.filter(owner=request.user)
    archived = request.GET.get("archived") == "on"
    query = query.filter(is_archived=archived)
    selected_project = None
    project_id = request.GET.get("project", "")
    if project_id == "unassigned":
        query = query.filter(research_item__project__isnull=True)
    elif project_id:
        selected_project = owned_project(request.user, project_id)
        query = query.filter(research_item__project=selected_project)
    material_type = request.GET.get("type", "")
    if material_type == "unclassified":
        query = query.filter(research_item__isnull=True)
    elif material_type:
        if material_type not in ResearchItem.MaterialType.values:
            raise Http404
        query = query.filter(research_item__material_type=material_type)
    stage = request.GET.get("stage", "")
    if stage:
        if stage not in ResearchItem.ReadingStage.values:
            raise Http404
        if stage == ResearchItem.ReadingStage.READING:
            query = query.filter(unread=True, research_item__reading_stage=stage)
        elif stage == ResearchItem.ReadingStage.USED:
            query = query.filter(unread=False, research_item__reading_stage=stage)
        elif stage == ResearchItem.ReadingStage.COLLECTED:
            query = query.filter(unread=True).exclude(
                research_item__reading_stage=ResearchItem.ReadingStage.READING
            )
        else:
            query = query.filter(unread=False).exclude(
                research_item__reading_stage=ResearchItem.ReadingStage.USED
            )
    organization = request.GET.get("organization", "")
    if organization == "pending":
        query = query.exclude(research_record_condition())
    elif organization == "recorded":
        query = query.filter(research_record_condition())
    elif organization:
        raise Http404
    text = request.GET.get("q", "").strip()
    if text:
        fields = (
            "title",
            "description",
            "url",
            "notes",
            "research_item__question",
            "research_item__conclusion",
            "research_item__evidence",
            "research_item__limitations",
            "research_item__relevance",
        )
        condition = Q()
        for field in fields:
            condition |= Q(**{field + "__icontains": text})
        condition |= Q(research_excerpts__is_archived=False) & (
            Q(research_excerpts__original_text__icontains=text)
            | Q(research_excerpts__interpretation__icontains=text)
            | Q(research_excerpts__locator__icontains=text)
        )
        query = query.filter(
            condition | Q(tags__name__icontains=text.lstrip("#"))
        ).distinct()
    return query.select_related(
        "research_item", "research_item__project"
    ).prefetch_related("tags").order_by("-date_modified", "-id"), selected_project


@login_required
@require_safe
def index(request):
    query, selected_project = materials_query(request)
    page = Paginator(query, 24).get_page(request.GET.get("page"))
    for bookmark in page.object_list:
        decorate_material(bookmark)
    projects = ResearchProject.objects.filter(owner=request.user).annotate(
        material_count=Count(
            "items",
            filter=Q(
                items__bookmark__owner=request.user, items__bookmark__is_archived=False
            ),
        )
    )
    owned = Bookmark.objects.filter(owner=request.user, is_archived=False)
    params = request.GET.copy()
    params.pop("page", None)
    organization_urls = {}
    for value in ("", "pending", "recorded"):
        tab_params = params.copy()
        tab_params.pop("organization", None)
        if value:
            tab_params["organization"] = value
        organization_urls[value or "all"] = reverse("research:index") + (
            "?" + tab_params.urlencode() if tab_params else ""
        )
    record_count = owned.filter(research_record_condition()).count()
    total_count = owned.count()
    context = {
        "page_title": "研究资料 · 源笺",
        "page": page,
        "projects": projects,
        "selected_project": selected_project,
        "filter_project": request.GET.get("project", ""),
        "filter_type": request.GET.get("type", ""),
        "filter_stage": request.GET.get("stage", ""),
        "filter_q": request.GET.get("q", ""),
        "filter_archived": request.GET.get("archived") == "on",
        "filter_organization": request.GET.get("organization", ""),
        "organization_urls": organization_urls,
        "capture_url": capture_url(selected_project),
        "material_types": ResearchItem.MaterialType.choices,
        "reading_stages": ResearchItem.ReadingStage.choices,
        "filter_query": params.urlencode(),
        "export_url": reverse("research:export")
        + ("?" + params.urlencode() if params else ""),
        "total_count": total_count,
        "pending_count": total_count - record_count,
        "record_count": record_count,
        "project_count": projects.count(),
    }
    return render(request, "research/index.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def material_edit(request, bookmark_id=None):
    bookmark = (
        get_object_or_404(Bookmark, pk=bookmark_id, owner=request.user)
        if bookmark_id is not None
        else None
    )
    initial = {
        "url": request.GET.get("url", request.GET.get("text", "")),
        "title": request.GET.get("title", ""),
    }
    selected_project = None
    if bookmark is None and request.GET.get("project") not in (None, "", "unassigned"):
        selected_project = owned_project(request.user, request.GET["project"])
        initial["project"] = selected_project.pk
    form = MaterialForm(
        request.user,
        request.POST if request.method == "POST" else None,
        instance=bookmark,
        initial=initial if bookmark is None else None,
    )
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        return redirect("research:material_detail", bookmark_id=saved.pk)
    return render(
        request,
        "research/material_form.html",
        {
            "page_title": ("编辑资料" if bookmark else "收集资料") + " · 源笺",
            "form": form,
            "bookmark": bookmark,
            "card_fields": [form[name] for name in form.card_fields],
            "duplicate_bookmark": form.duplicate_bookmark,
            "capture_url": capture_url(selected_project),
        },
        status=422 if request.method == "POST" else 200,
    )


@login_required
@require_safe
def material_detail(request, bookmark_id):
    bookmark = get_object_or_404(
        Bookmark.objects.select_related(
            "research_item", "research_item__project"
        ).prefetch_related("tags"),
        pk=bookmark_id,
        owner=request.user,
    )
    decorate_material(bookmark)
    item = bookmark.card
    sections = (
        [
            (label, getattr(item, field))
            for field, label in (
                ("question", "研究问题"),
                ("conclusion", "核心结论"),
                ("evidence", "证据与实验"),
                ("limitations", "局限与注意事项"),
                ("relevance", "与课题的关系"),
            )
        ]
        if item
        else []
    )
    return render(
        request,
        "research/material_detail.html",
        {
            "page_title": bookmark.resolved_title + " · 源笺",
            "bookmark": bookmark,
            "sections": sections,
            "excerpts": ResearchExcerpt.objects.filter(
                bookmark=bookmark, is_archived=False
            ),
            "removed_excerpts": ResearchExcerpt.objects.filter(
                bookmark=bookmark, is_archived=True
            ),
            "capture_url": capture_url(item.project if item else None),
        },
    )


@login_required
@require_POST
def metadata(request):
    form = MetadataLookupForm(request.POST)
    if not form.is_valid():
        response = JsonResponse(
            {"available": False, "message": str(form.errors["url"][0])}, status=400
        )
    else:
        result = website_loader.load_website_metadata(
            form.cleaned_data["url"], trust_env=False
        )
        title = (result.title or "").strip()[:512]
        description = (result.description or "").strip()[:20000]
        response = JsonResponse(
            {
                "available": bool(title or description),
                "title": title,
                "description": description,
                "message": ""
                if title or description
                else "未能读取资料信息，你仍可以手动填写并保存。",
            }
        )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_safe
def projects(request):
    owned = ResearchProject.objects.filter(owner=request.user).annotate(
        material_count=Count("items", filter=Q(items__bookmark__owner=request.user))
    )
    return render(
        request,
        "research/projects.html",
        {"page_title": "我的课题 · 源笺", "projects": owned},
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_edit(request, project_id=None):
    project = (
        get_object_or_404(ResearchProject, pk=project_id, owner=request.user)
        if project_id is not None
        else None
    )
    form = ProjectForm(
        request.user,
        request.POST if request.method == "POST" else None,
        instance=project,
    )
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        return redirect(reverse("research:index") + f"?project={saved.pk}")
    return render(
        request,
        "research/project_form.html",
        {
            "page_title": ("编辑课题" if project else "新建课题") + " · 源笺",
            "form": form,
            "project": project,
            "capture_url": capture_url(project),
        },
        status=422 if request.method == "POST" else 200,
    )


@login_required
@require_safe
def export(request):
    query, project = materials_query(request)
    query = query.prefetch_related(
        Prefetch(
            "research_excerpts",
            queryset=ResearchExcerpt.objects.filter(is_archived=False),
            to_attr="active_excerpts",
        )
    )
    now = timezone.localtime()
    title = project.name + " · 研究材料" if project else "研究材料清单"
    response = StreamingHttpResponse(
        export_markdown(query, title, now.strftime("%Y-%m-%d %H:%M %Z")),
        content_type="text/markdown; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="yuanjian-research-{now:%Y-%m-%d}.md"'
    )
    response["Cache-Control"] = "private, no-store"
    return response
