from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        (
            "assistant",
            "0004_projectassistantthread_and_message_thread",
        ),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="projectassistantmessage",
            old_name="assistant_p_thread__299dbf_idx",
            new_name="assistant_p_thread__f702c1_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantthread",
            old_name="assistant_p_project_f257f8_idx",
            new_name="assistant_p_project_68179f_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantthread",
            old_name="assistant_p_project_aeed2b_idx",
            new_name="assistant_p_project_51bb12_idx",
        ),
    ]
