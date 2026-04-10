from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        (
            "projects",
            "0002_projectpostseenstate",
        ),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="projectpostseenstate",
            old_name="projects_pr_profile_d0de4f_idx",
            new_name="projects_pr_profile_e61b4b_idx",
        ),
        migrations.RenameIndex(
            model_name="projectpostseenstate",
            old_name="projects_pr_post_id_639955_idx",
            new_name="projects_pr_post_id_a2824c_idx",
        ),
    ]
