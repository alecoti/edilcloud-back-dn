import colorsys

from django.db import migrations, models


PROJECT_COMPANY_COLOR_PALETTE = [
    "#2563eb",
    "#ea580c",
    "#0f766e",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#65a30d",
    "#c2410c",
    "#db2777",
    "#4f46e5",
    "#0d9488",
    "#9333ea",
    "#b91c1c",
    "#0284c7",
    "#15803d",
    "#d97706",
    "#be185d",
    "#1d4ed8",
]


def build_project_company_color(project_id: int, attempt_index: int) -> str:
    palette_size = len(PROJECT_COMPANY_COLOR_PALETTE)
    if attempt_index < palette_size:
        return PROJECT_COMPANY_COLOR_PALETTE[(project_id + attempt_index) % palette_size]

    offset = attempt_index - palette_size
    hue = (((project_id * 47) + (offset * 137.508)) % 360) / 360
    lightness = 0.46 if offset % 2 == 0 else 0.4
    saturation = 0.72
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def pick_next_color(project_id: int, used_colors: set[str]) -> str:
    candidate_index = 0
    while True:
        candidate = build_project_company_color(project_id, candidate_index)
        candidate_index += 1
        if candidate not in used_colors:
            return candidate


def backfill_project_company_colors(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    ProjectCompanyColor = apps.get_model("projects", "ProjectCompanyColor")
    ProjectMember = apps.get_model("projects", "ProjectMember")
    ProjectTask = apps.get_model("projects", "ProjectTask")

    for project in Project.objects.all().order_by("id"):
        ordered_workspace_ids = []
        seen_workspace_ids = set()

        def add_workspace_id(value):
            if not value or value in seen_workspace_ids:
                return
            seen_workspace_ids.add(value)
            ordered_workspace_ids.append(value)

        members = (
            ProjectMember.objects.select_related("profile")
            .filter(project_id=project.id, disabled=False)
            .order_by("created_at", "id")
        )
        for member in members:
            add_workspace_id(getattr(member.profile, "workspace_id", None))

        tasks = (
            ProjectTask.objects.filter(project_id=project.id, assigned_company_id__isnull=False)
            .order_by("created_at", "id")
        )
        for task in tasks:
            add_workspace_id(task.assigned_company_id)

        used_colors = set()
        for workspace_id in ordered_workspace_ids:
            color_project = pick_next_color(project.id, used_colors)
            used_colors.add(color_project)
            ProjectCompanyColor.objects.create(
                project_id=project.id,
                workspace_id=workspace_id,
                color_project=color_project,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0004_projectoperationalevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectCompanyColor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("color_project", models.CharField(max_length=16)),
                ("project", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="company_colors", to="projects.project")),
                ("workspace", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="project_colors", to="workspaces.workspace")),
            ],
            options={
                "ordering": ("project_id", "id"),
                "indexes": [models.Index(fields=["project", "workspace"], name="projects_pro_project_540f4a_idx")],
                "constraints": [
                    models.UniqueConstraint(fields=("project", "workspace"), name="unique_project_company_color"),
                ],
            },
        ),
        migrations.RunPython(backfill_project_company_colors, migrations.RunPython.noop),
    ]
