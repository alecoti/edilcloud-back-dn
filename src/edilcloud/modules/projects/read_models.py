"""Shared read projections; directories retain the full existing profile contract."""
def read_profile(profile, *, directory=None, company_colors_by_workspace_id=None):
    if profile is None:
        return None
    from edilcloud.modules.projects.services import serialize_project_profile
    if directory is None:
        return serialize_project_profile(profile, company_colors_by_workspace_id=company_colors_by_workspace_id)
    if profile.id not in directory:
        directory[profile.id] = serialize_project_profile(profile, company_colors_by_workspace_id=company_colors_by_workspace_id)
    return {"id": profile.id}
