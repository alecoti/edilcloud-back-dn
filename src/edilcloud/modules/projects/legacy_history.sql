-- Read-only legacy candidates. The parent query defines args(project,profile,workspace,mode,task,activity).
WITH source_posts AS (
 SELECT p.*, COALESCE(p.task_id, act.task_id) AS scope_task_id,
        pr.name AS project_name,t.name AS task_name,act.title AS activity_title
 FROM projects_projectpost p CROSS JOIN args arg
 JOIN projects_project pr ON pr.id=arg.project
 LEFT JOIN projects_projectactivity act ON act.id=p.activity_id
 LEFT JOIN projects_projecttask t ON t.id=COALESCE(p.task_id,act.task_id)
 WHERE p.project_id=arg.project
 AND EXISTS(SELECT 1 FROM projects_projectmember m
   JOIN workspaces_profile vp ON vp.id=m.profile_id
   JOIN workspaces_workspace vw ON vw.id=vp.workspace_id
   JOIN identity_user vu ON vu.id=vp.user_id
   WHERE m.project_id=p.project_id AND m.profile_id=arg.profile
   AND m.status=1 AND NOT m.disabled AND vp.is_active AND vw.is_active AND vu.is_active
   AND vp.workspace_id=arg.workspace)
 AND (COALESCE(p.task_id,act.task_id) IS NULL OR t.project_id=p.project_id)
 AND (p.activity_id IS NULL OR act.task_id=t.id)
 AND (p.task_id IS NULL OR p.activity_id IS NULL OR p.task_id=act.task_id)
 AND (arg.mode='project'
   OR (arg.mode='activity' AND p.activity_id=arg.activity)
   OR (arg.mode='general' AND COALESCE(p.task_id,act.task_id)=arg.task AND p.activity_id IS NULL)
   OR (arg.mode='phase' AND (COALESCE(p.task_id,act.task_id)=arg.task
       OR (p.task_id IS NULL AND p.activity_id IS NULL))))
), candidates AS (
 SELECT COALESCE(p.published_date,p.created_at) AS at,'post'::text AS origin,p.id AS entity,0 AS kind,
        'post.created'::text AS event_type,p.id AS post_id,NULL::bigint AS comment_id,
        p.author_id AS event_author_id,p.text AS event_text,p.is_deleted AS event_deleted,NULL::bigint AS parent_id,p.project_id,p.scope_task_id,p.activity_id,p.project_name,p.task_name,p.activity_title,p.post_kind,p.is_public,p.alert,p.weather_snapshot
 FROM source_posts p
 UNION ALL
 SELECT p.edited_at,'post',p.id,1,'post.updated',p.id,NULL,NULL,p.text,p.is_deleted,NULL,p.project_id,p.scope_task_id,p.activity_id,p.project_name,p.task_name,p.activity_title,p.post_kind,p.is_public,p.alert,p.weather_snapshot
 FROM source_posts p
 WHERE p.edited_at>COALESCE(p.published_date,p.created_at)
 UNION ALL
 SELECT p.deleted_at,'post',p.id,2,'post.deleted',p.id,NULL,NULL,''::text,TRUE,NULL,p.project_id,p.scope_task_id,p.activity_id,p.project_name,p.task_name,p.activity_title,p.post_kind,p.is_public,p.alert,p.weather_snapshot
 FROM source_posts p WHERE p.deleted_at IS NOT NULL
 UNION ALL
 SELECT CASE WHEN c.deleted_at IS NOT NULL AND c.deleted_at>=c.created_at
                 AND (c.edited_at IS NULL OR c.deleted_at>=c.edited_at) THEN c.deleted_at
             WHEN c.edited_at>c.created_at THEN c.edited_at ELSE c.created_at END,
        'comment',c.id,
        CASE WHEN c.deleted_at IS NOT NULL AND c.deleted_at>=c.created_at
                 AND (c.edited_at IS NULL OR c.deleted_at>=c.edited_at) THEN 2
             WHEN c.edited_at>c.created_at THEN 1 ELSE 0 END,
        CASE WHEN c.deleted_at IS NOT NULL AND c.deleted_at>=c.created_at
                 AND (c.edited_at IS NULL OR c.deleted_at>=c.edited_at) THEN 'comment.deleted'
             WHEN c.edited_at>c.created_at THEN 'comment.updated' ELSE 'comment.created' END,
        p.id,c.id,
        CASE WHEN c.edited_at>c.created_at OR c.deleted_at IS NOT NULL THEN NULL ELSE c.author_id END,
        c.text,c.is_deleted OR p.is_deleted,c.parent_id,p.project_id,p.scope_task_id,p.activity_id,p.project_name,p.task_name,p.activity_title,p.post_kind,p.is_public,p.alert,p.weather_snapshot
 FROM source_posts p JOIN projects_postcomment c ON c.post_id=p.id
), selected AS (
 SELECT c.* FROM candidates c
 WHERE c.at IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM projects_projectoperationalevent e
  WHERE e.project_id=c.project_id AND jsonb_typeof(e.payload->'timeline')='object'
  AND CASE WHEN c.origin='comment'
      THEN (e.comment_id_snapshot=c.comment_id OR e.payload->>'commentId'=c.comment_id::text)
      ELSE (e.post_id_snapshot=c.post_id OR e.payload->>'postId'=c.post_id::text)
           AND e.comment_id_snapshot IS NULL END
  AND (e.event_type=c.event_type OR(c.event_type='post.updated' AND e.event_type='post.resolved'))
  AND (c.kind=0 OR e.occurred_at>=c.at)
 )
)
SELECT c.at,c.origin,c.entity,c.kind,
 jsonb_build_object(
  'eventId',concat('legacy:',c.origin,':',c.entity,':',c.kind),
  'type',c.event_type,'timestamp',c.at,'projectId',c.project_id,
  'taskId',c.scope_task_id,'activityId',c.activity_id,'postId',c.post_id,'commentId',c.comment_id,
  'profileId',c.event_author_id,
  'actor',jsonb_build_object('firstName',a.first_name,'lastName',a.last_name),
  'data',jsonb_build_object(
   'project_name',c.project_name,'task_name',c.task_name,'activity_title',c.activity_title,
   'project_level',c.scope_task_id IS NULL AND c.activity_id IS NULL,
   'category',c.origin,'post_kind',c.post_kind,'is_public',c.is_public,'alert',c.alert,
   'is_deleted',c.event_deleted,'parent_id',c.parent_id,'attachment_count',0,
   'actor_name',CASE WHEN c.event_author_id IS NOT NULL THEN NULL
      WHEN c.kind=2 THEN 'Autore eliminazione non registrato' ELSE 'Autore modifica non registrato' END,
   'excerpt',CASE WHEN c.event_deleted THEN '' ELSE left(c.event_text,180) END,
   'weather_snapshot',CASE WHEN c.origin='post' THEN c.weather_snapshot ELSE NULL END
  ),
  'reconstruction',jsonb_build_object('record_type',c.origin,'record_id',c.entity,
    'timestamp_field',CASE WHEN c.kind=2 THEN 'deleted_at' WHEN c.kind=1 THEN 'edited_at'
       WHEN c.origin='post' THEN 'published_date' ELSE 'created_at' END,
    'content_basis','current_record','actor_basis',CASE WHEN c.event_author_id IS NULL THEN 'unknown' ELSE 'record_author' END)
 ) AS payload
FROM selected c LEFT JOIN workspaces_profile a ON a.id=c.event_author_id
