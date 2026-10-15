"""Isolated local SQLite fixture; never run against production settings."""
import json
from datetime import date
from django.conf import settings
from django.contrib.auth import get_user_model
from edilcloud.modules.projects.models import Project, ProjectMember
from edilcloud.modules.workspaces.models import Workspace, Profile

assert settings.DATABASES['default']['ENGINE'].endswith('sqlite3'), 'Only the local SQLite QA database is allowed'
assert not settings.FCM_PUSH_ENABLED, 'External delivery must stay disabled in this fixture'
workspace, _ = Workspace.objects.get_or_create(name='QA impostazioni 20261015')
profiles = []
for role, email, name in [('o','qa.project.owner@example.test','Laura Verdi'),('w','qa.project.worker@example.test','Mario Rossi')]:
    user, _ = get_user_model().objects.get_or_create(email=email,defaults={'username':email})
    user.set_password('settings-local-qa-123'); user.save()
    profile, _ = Profile.objects.get_or_create(user=user,workspace=workspace,defaults={'email':email,'role':role,'first_name':name.split()[0],'last_name':name.split()[1]})
    profiles.append(profile)
project, _ = Project.objects.get_or_create(workspace=workspace,name='QA impostazioni progetto',defaults={'date_start':date(2026,10,1),'created_by':profiles[0]})
for profile in profiles:
    ProjectMember.objects.update_or_create(project=project,profile=profile,defaults={'role':profile.role,'status':1,'disabled':False,'notification_preferences':{}})
print(json.dumps({'project_id':project.id,'owner_profile':profiles[0].id,'worker_profile':profiles[1].id}))
