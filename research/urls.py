from django.urls import path

from . import views

app_name = "research"
urlpatterns = [
    path("", views.index, name="index"),
    path("materials/new", views.material_edit, name="material_new"),
    path("materials/metadata", views.metadata, name="metadata"),
    path("materials/<int:bookmark_id>", views.material_detail, name="material_detail"),
    path("materials/<int:bookmark_id>/edit", views.material_edit, name="material_edit"),
    path("projects", views.projects, name="projects"),
    path("projects/new", views.project_edit, name="project_new"),
    path("projects/<int:project_id>/edit", views.project_edit, name="project_edit"),
    path("export", views.export, name="export"),
]
