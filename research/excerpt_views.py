from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
    require_safe,
)

from bookmarks.models import Bookmark

from .forms import ExcerptForm, ExcerptSelectionForm
from .models import ResearchExcerpt, ResearchProject
from .services import export_excerpts_markdown
from .views import capture_url, owned_project


def excerpts_query(request):
    query = ResearchExcerpt.objects.filter(
        bookmark__owner=request.user, is_archived=False
    )
    if request.GET.get("include_archived") != "on":
        query = query.filter(bookmark__is_archived=False)
    project_id = request.GET.get("project", "")
    project = None
    if project_id == "unassigned":
        query = query.filter(bookmark__research_item__project__isnull=True)
    elif project_id:
        project = owned_project(request.user, project_id)
        query = query.filter(bookmark__research_item__project=project)
    text = request.GET.get("q", "").strip()
    if text:
        condition = Q()
        for field in (
            "original_text",
            "interpretation",
            "locator",
            "bookmark__title",
            "bookmark__url",
        ):
            condition |= Q(**{field + "__icontains": text})
        query = query.filter(condition)
    return query.select_related(
        "bookmark", "bookmark__research_item", "bookmark__research_item__project"
    ), project


def render_excerpt_index(request, query, project, selection_form=None, status=200):
    page = Paginator(query, 24).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    export_url = reverse("research:excerpt_export")
    if params:
        export_url += "?" + params.urlencode()
    selected_ids = set(request.POST.getlist("selected")) if selection_form else set()
    return render(
        request,
        "research/excerpts.html",
        {
            "page_title": "研究摘录 · 源笺",
            "page": page,
            "projects": ResearchProject.objects.filter(owner=request.user),
            "selected_project": project,
            "filter_project": request.GET.get("project", ""),
            "filter_q": request.GET.get("q", ""),
            "include_archived": request.GET.get("include_archived") == "on",
            "filter_query": params.urlencode(),
            "export_url": export_url,
            "selection_form": selection_form,
            "selected_ids": selected_ids,
            "capture_url": capture_url(project),
        },
        status=status,
    )


@login_required
@require_safe
def index(request):
    query, project = excerpts_query(request)
    return render_excerpt_index(request, query, project)


@login_required
@require_http_methods(["GET", "POST"])
def edit(request, bookmark_id, excerpt_id=None):
    bookmark = get_object_or_404(Bookmark, pk=bookmark_id, owner=request.user)
    excerpt = (
        get_object_or_404(
            ResearchExcerpt, pk=excerpt_id, bookmark=bookmark, is_archived=False
        )
        if excerpt_id is not None
        else ResearchExcerpt(bookmark=bookmark)
    )
    form = ExcerptForm(
        request.POST if request.method == "POST" else None, instance=excerpt
    )
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        return redirect(
            reverse("research:material_detail", args=[bookmark.pk])
            + f"#excerpt-{saved.pk}"
        )
    card = getattr(bookmark, "research_item", None)
    return render(
        request,
        "research/excerpt_form.html",
        {
            "page_title": ("编辑摘录" if excerpt_id else "新增摘录") + " · 源笺",
            "bookmark": bookmark,
            "excerpt": excerpt,
            "form": form,
            "capture_url": capture_url(card.project if card else None),
        },
        status=422 if request.method == "POST" else 200,
    )


@login_required
@require_POST
def archive(request, bookmark_id, excerpt_id):
    excerpt = get_object_or_404(
        ResearchExcerpt,
        pk=excerpt_id,
        bookmark_id=bookmark_id,
        bookmark__owner=request.user,
    )
    # Removal is reversible from the material detail page.
    excerpt.is_archived = request.POST.get("restore") != "on"
    excerpt.save(update_fields=["is_archived", "updated_at"])
    return redirect(
        reverse("research:material_detail", args=[bookmark_id]) + "#research-excerpts"
    )


@login_required
@require_POST
def export(request):
    query, project = excerpts_query(request)
    form = ExcerptSelectionForm(query, request.POST)
    if not form.is_valid():
        return render_excerpt_index(request, query, project, form, status=422)
    now = timezone.localtime()
    title = project.name + " · 研究摘录" if project else "研究摘录清单"
    response = StreamingHttpResponse(
        export_excerpts_markdown(
            form.cleaned_data["selected"], title, now.strftime("%Y-%m-%d %H:%M %Z")
        ),
        content_type="text/markdown; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="yuanjian-excerpts-{now:%Y-%m-%d}.md"'
    )
    response["Cache-Control"] = "private, no-store"
    return response
