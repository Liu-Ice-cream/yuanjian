from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
    require_safe,
)

from .forms import ExcerptSelectionForm, GroupForm, OrderForm, PlacementMoveForm
from .models import ResearchGroup, ResearchProject
from .outline_services import (
    add_excerpts,
    available_excerpts,
    available_placements,
    export_outline_markdown,
    next_position,
    outlined_groups,
    reorder,
)
from .views import capture_url, owned_project


def locked_project(user, project_id):
    project = owned_project(user, project_id)
    return ResearchProject.objects.select_for_update().get(pk=project.pk)


def group_url(group):
    return reverse("research:group_detail", args=[group.project_id, group.pk])


def board_url(project):
    return reverse("research:outline", args=[project.pk])


def owned_group(project, group_id):
    return get_object_or_404(
        ResearchGroup, pk=group_id, project=project, is_archived=False
    )


def group_context(project, group):
    placements = list(available_placements(project).filter(group=group))
    for placement in placements:
        placement.move_form = PlacementMoveForm(group)
    return {
        "project": project,
        "group": group,
        "placements": placements,
        "unavailable_count": group.placements.filter(is_archived=False).count()
        - len(placements),
        "capture_url": capture_url(project),
    }


@login_required
@require_safe
def board(request, project_id):
    project = owned_project(request.user, project_id)
    groups = list(outlined_groups(project))
    for group in groups:
        group.unavailable_count = group.saved_count - len(group.visible_placements)
    return render(
        request,
        "research/outline.html",
        {
            "page_title": "课题材料编排 · 源笺",
            "project": project,
            "groups": groups,
            "removed_groups": ResearchGroup.objects.filter(
                project=project, is_archived=True
            ),
            "capture_url": capture_url(project),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def group_edit(request, project_id, group_id=None):
    project = (
        locked_project(request.user, project_id)
        if request.method == "POST"
        else owned_project(request.user, project_id)
    )
    group = (
        owned_group(project, group_id) if group_id else ResearchGroup(project=project)
    )
    form = GroupForm(request.POST if request.method == "POST" else None, instance=group)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if not saved.pk:
            saved.position = next_position(project.material_groups.all())
        saved.save()
        return redirect(group_url(saved))
    return render(
        request,
        "research/group_form.html",
        {
            "page_title": ("编辑分组" if group_id else "新建材料分组") + " · 源笺",
            "project": project,
            "group": group,
            "form": form,
            "capture_url": capture_url(project),
        },
        status=422 if request.method == "POST" else 200,
    )


def eligible_excerpts(request, project):
    query = available_excerpts(project)
    text = request.GET.get("q", "").strip()
    if text:
        query = query.filter(
            Q(original_text__icontains=text)
            | Q(interpretation__icontains=text)
            | Q(locator__icontains=text)
            | Q(bookmark__title__icontains=text)
        )
    return query


def render_group_detail(
    request, project, group, selection_form=None, move_error=None, status=200
):
    context = group_context(project, group)
    candidates = eligible_excerpts(request, project).exclude(
        pk__in=group.placements.filter(is_archived=False).values("excerpt_id")
    )
    params = request.GET.copy()
    params.pop("page", None)
    add_url = reverse("research:group_add", args=[project.pk, group.pk])
    if params:
        add_url += "?" + params.urlencode()
    context.update(
        {
            "page_title": group.name + " · 材料分组 · 源笺",
            "page": Paginator(candidates, 24).get_page(request.GET.get("page")),
            "filter_q": request.GET.get("q", ""),
            "filter_query": params.urlencode(),
            "add_url": add_url,
            "selection_form": selection_form,
            "move_error": move_error,
            "selected_ids": set(request.POST.getlist("selected"))
            if selection_form
            else set(),
        }
    )
    return render(request, "research/group_detail.html", context, status=status)


@login_required
@require_safe
def group_detail(request, project_id, group_id):
    project = owned_project(request.user, project_id)
    return render_group_detail(request, project, owned_group(project, group_id))


@login_required
@require_POST
@transaction.atomic
def group_add(request, project_id, group_id):
    project = locked_project(request.user, project_id)
    group = owned_group(project, group_id)
    form = ExcerptSelectionForm(eligible_excerpts(request, project), request.POST)
    form.fields["selected"].error_messages["required"] = "请先勾选需要加入分组的摘录。"
    if not form.is_valid():
        return render_group_detail(request, project, group, form, status=422)
    add_excerpts(group, form.cleaned_data["selected"].order_by("created_at", "pk"))
    return redirect(group_url(group))


@login_required
@require_POST
@transaction.atomic
def group_archive(request, project_id, group_id):
    project = locked_project(request.user, project_id)
    group = get_object_or_404(ResearchGroup, pk=group_id, project=project)
    if request.POST.get("restore") == "on":
        if group.is_archived:
            group.is_archived = False
            group.position = next_position(project.material_groups.all())
    else:
        group.is_archived = True
    group.save(update_fields=["is_archived", "position", "updated_at"])
    return redirect(board_url(project))


@login_required
@require_POST
@transaction.atomic
def group_order(request, project_id, group_id):
    project = locked_project(request.user, project_id)
    group = owned_group(project, group_id)
    form = OrderForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("请选择上移或下移。")
    reorder(
        project.material_groups.filter(is_archived=False),
        group,
        form.cleaned_data["direction"],
    )
    return redirect(board_url(project))


@login_required
@require_POST
@transaction.atomic
def placement_action(request, project_id, group_id, placement_id, action):
    project = locked_project(request.user, project_id)
    group = owned_group(project, group_id)
    placement = get_object_or_404(
        available_placements(project), pk=placement_id, group=group
    )
    if action == "order":
        form = OrderForm(request.POST)
        if not form.is_valid():
            return HttpResponseBadRequest("请选择上移或下移。")
        reorder(
            available_placements(project).filter(group=group),
            placement,
            form.cleaned_data["direction"],
        )
    elif action == "remove":
        placement.is_archived = True
        placement.save(update_fields=["is_archived"])
    elif action == "move":
        form = PlacementMoveForm(group, request.POST)
        if not form.is_valid():
            return render_group_detail(
                request, project, group, move_error=form.errors["target"], status=422
            )
        add_excerpts(form.cleaned_data["target"], [placement.excerpt])
        placement.is_archived = True
        placement.save(update_fields=["is_archived"])
    return redirect(group_url(group))


@login_required
@require_safe
def export(request, project_id):
    project = owned_project(request.user, project_id)
    groups = list(outlined_groups(project))
    now = timezone.localtime()
    response = StreamingHttpResponse(
        export_outline_markdown(project, groups, now.strftime("%Y-%m-%d %H:%M %Z")),
        content_type="text/markdown; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="yuanjian-outline-{now:%Y-%m-%d}.md"'
    )
    response["Cache-Control"] = "private, no-store"
    return response
