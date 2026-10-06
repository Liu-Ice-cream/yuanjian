from django.urls import path

from . import excerpt_views, outline_views, paper_views, views

app_name = "research"
urlpatterns = [
    path("materials/<int:bookmark_id>/paper", paper_views.edit, name="paper_edit"),
    path(
        "projects/<int:project_id>/citations", paper_views.citations, name="citations"
    ),
    path(
        "projects/<int:project_id>/citations/export",
        paper_views.export,
        name="citations_export",
    ),
    path("projects/<int:project_id>/outline", outline_views.board, name="outline"),
    path(
        "projects/<int:project_id>/outline/export",
        outline_views.export,
        name="outline_export",
    ),
    path(
        "projects/<int:project_id>/outline/groups/new",
        outline_views.group_edit,
        name="group_new",
    ),
    path(
        "projects/<int:project_id>/outline/groups/<int:group_id>",
        outline_views.group_detail,
        name="group_detail",
    ),
    path(
        "projects/<int:project_id>/outline/groups/<int:group_id>/edit",
        outline_views.group_edit,
        name="group_edit",
    ),
    path(
        "projects/<int:project_id>/outline/groups/<int:group_id>/add",
        outline_views.group_add,
        name="group_add",
    ),
    path(
        "projects/<int:project_id>/outline/groups/<int:group_id>/archive",
        outline_views.group_archive,
        name="group_archive",
    ),
    path(
        "projects/<int:project_id>/outline/groups/<int:group_id>/order",
        outline_views.group_order,
        name="group_order",
    ),
    path(
        "projects/<int:project_id>/outline/groups/<int:group_id>/placements/<int:placement_id>/order",
        outline_views.placement_action,
        {"action": "order"},
        name="placement_order",
    ),
    path(
        "projects/<int:project_id>/outline/groups/<int:group_id>/placements/<int:placement_id>/remove",
        outline_views.placement_action,
        {"action": "remove"},
        name="placement_remove",
    ),
    path(
        "projects/<int:project_id>/outline/groups/<int:group_id>/placements/<int:placement_id>/move",
        outline_views.placement_action,
        {"action": "move"},
        name="placement_move",
    ),
    path("", views.index, name="index"),
    path("materials/new", views.material_edit, name="material_new"),
    path("materials/metadata", views.metadata, name="metadata"),
    path("materials/<int:bookmark_id>", views.material_detail, name="material_detail"),
    path("materials/<int:bookmark_id>/edit", views.material_edit, name="material_edit"),
    path("projects", views.projects, name="projects"),
    path("projects/new", views.project_edit, name="project_new"),
    path("projects/<int:project_id>/edit", views.project_edit, name="project_edit"),
    path("export", views.export, name="export"),
    path("excerpts", excerpt_views.index, name="excerpts"),
    path("excerpts/export", excerpt_views.export, name="excerpt_export"),
    path(
        "materials/<int:bookmark_id>/excerpts/new",
        excerpt_views.edit,
        name="excerpt_new",
    ),
    path(
        "materials/<int:bookmark_id>/excerpts/<int:excerpt_id>/edit",
        excerpt_views.edit,
        name="excerpt_edit",
    ),
    path(
        "materials/<int:bookmark_id>/excerpts/<int:excerpt_id>/archive",
        excerpt_views.archive,
        name="excerpt_archive",
    ),
]
