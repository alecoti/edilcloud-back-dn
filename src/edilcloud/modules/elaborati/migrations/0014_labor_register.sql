-- Shared Django/SQLx schema for company-private labor records. No backfill.
SET LOCAL search_path TO public;
DO $labor$
DECLARE existing integer; item record;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('edilcloud:labor-register-v1',0));
 SELECT count(*) INTO existing FROM (VALUES
 ('elaborati_laboridentity'),('elaborati_laborregister'),('elaborati_laborrevision'),('elaborati_laboroperation')
 ) x(name) WHERE to_regclass('public.'||name) IS NOT NULL;
 IF existing=0 THEN
 --
-- Create model LaborIdentity
--
CREATE TABLE "elaborati_laboridentity" ("id" uuid NOT NULL PRIMARY KEY, "kind" varchar(8) NOT NULL, "name" varchar(200) NOT NULL, "external_reference" varchar(100) NOT NULL, "basis" varchar(16) NOT NULL, "active" boolean NOT NULL, "created_at" timestamp with time zone NOT NULL, "updated_at" timestamp with time zone NOT NULL, "created_by_id" bigint NULL, "profile_id" bigint NULL, "workspace_id" bigint NOT NULL);
--
-- Create model LaborRegister
--
CREATE TABLE "elaborati_laborregister" ("id" uuid NOT NULL PRIMARY KEY, "current_version" integer NOT NULL CHECK ("current_version" >= 0), "effective_version" integer NULL CHECK ("effective_version" >= 0), "created_at" timestamp with time zone NOT NULL, "updated_at" timestamp with time zone NOT NULL, "created_by_id" bigint NULL, "project_id" bigint NOT NULL, "workspace_id" bigint NOT NULL);
--
-- Create model LaborRevision
--
CREATE TABLE "elaborati_laborrevision" ("id" uuid NOT NULL PRIMARY KEY, "number" integer NOT NULL CHECK ("number" >= 0), "state" varchar(16) NOT NULL, "work_date" date NOT NULL, "timezone" varchar(100) NOT NULL, "data" jsonb NOT NULL, "content_hash" varchar(64) NOT NULL, "actor_snapshot" jsonb NOT NULL, "action" varchar(16) NOT NULL, "reason" varchar(1000) NOT NULL, "review_mode" varchar(16) NOT NULL, "replaces_version" integer NULL CHECK ("replaces_version" >= 0), "created_at" timestamp with time zone NOT NULL, "actor_id" bigint NULL, "register_id" uuid NOT NULL);
--
-- Create model LaborOperation
--
CREATE TABLE "elaborati_laboroperation" ("id" uuid NOT NULL PRIMARY KEY, "actor_key" bigint NOT NULL, "command_id" uuid NOT NULL, "request_hash" varchar(64) NOT NULL, "created_at" timestamp with time zone NOT NULL, "identity_id" uuid NULL, "workspace_id" bigint NOT NULL, "register_id" uuid NULL, "revision_id" uuid NULL);
--
-- Create index labor_identity_catalog_idx on field(s) workspace, active, name of model laboridentity
--
CREATE INDEX "labor_identity_catalog_idx" ON "elaborati_laboridentity" ("workspace_id", "active", "name");
--
-- Create constraint labor_identity_profile_uq on model laboridentity
--
CREATE UNIQUE INDEX "labor_identity_profile_uq" ON "elaborati_laboridentity" ("workspace_id", "profile_id") WHERE "profile_id" IS NOT NULL;
--
-- Create constraint labor_identity_kind_ck on model laboridentity
--
ALTER TABLE "elaborati_laboridentity" ADD CONSTRAINT "labor_identity_kind_ck" CHECK ("kind" IN ('person', 'team'));
--
-- Create constraint labor_identity_basis_ck on model laboridentity
--
ALTER TABLE "elaborati_laboridentity" ADD CONSTRAINT "labor_identity_basis_ck" CHECK ("basis" IN ('profile', 'declared'));
--
-- Create index labor_register_scope_idx on field(s) workspace, project, -updated_at of model laborregister
--
CREATE INDEX "labor_register_scope_idx" ON "elaborati_laborregister" ("workspace_id", "project_id", "updated_at" DESC);
--
-- Create constraint labor_register_version_ck on model laborregister
--
ALTER TABLE "elaborati_laborregister" ADD CONSTRAINT "labor_register_version_ck" CHECK ("current_version" >= 1);
--
-- Create index labor_revision_day_idx on field(s) work_date, register of model laborrevision
--
CREATE INDEX "labor_revision_day_idx" ON "elaborati_laborrevision" ("work_date", "register_id");
--
-- Create constraint labor_revision_number_uq on model laborrevision
--
ALTER TABLE "elaborati_laborrevision" ADD CONSTRAINT "labor_revision_number_uq" UNIQUE ("register_id", "number");
--
-- Create constraint labor_revision_number_ck on model laborrevision
--
ALTER TABLE "elaborati_laborrevision" ADD CONSTRAINT "labor_revision_number_ck" CHECK ("number" >= 1);
--
-- Create constraint labor_revision_state_ck on model laborrevision
--
ALTER TABLE "elaborati_laborrevision" ADD CONSTRAINT "labor_revision_state_ck" CHECK ("state" IN ('draft', 'confirmed', 'submitted', 'approved', 'rejected'));
--
-- Create constraint labor_operation_idempotency on model laboroperation
--
ALTER TABLE "elaborati_laboroperation" ADD CONSTRAINT "labor_operation_idempotency" UNIQUE ("workspace_id", "actor_key", "command_id");
--
-- Create constraint labor_operation_target_ck on model laboroperation
--
ALTER TABLE "elaborati_laboroperation" ADD CONSTRAINT "labor_operation_target_ck" CHECK ((("identity_id" IS NOT NULL AND "register_id" IS NULL AND "revision_id" IS NULL) OR ("identity_id" IS NULL AND "register_id" IS NOT NULL AND "revision_id" IS NOT NULL)));
ALTER TABLE "elaborati_laboridentity" ADD CONSTRAINT "elaborati_laborident_created_by_id_47ecc7ef_fk_workspace" FOREIGN KEY ("created_by_id") REFERENCES "workspaces_profile" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laboridentity" ADD CONSTRAINT "elaborati_laborident_profile_id_0bdfb1f2_fk_workspace" FOREIGN KEY ("profile_id") REFERENCES "workspaces_profile" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laboridentity" ADD CONSTRAINT "elaborati_laborident_workspace_id_a651472a_fk_workspace" FOREIGN KEY ("workspace_id") REFERENCES "workspaces_workspace" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "elaborati_laboridentity_created_by_id_47ecc7ef" ON "elaborati_laboridentity" ("created_by_id");
CREATE INDEX "elaborati_laboridentity_profile_id_0bdfb1f2" ON "elaborati_laboridentity" ("profile_id");
CREATE INDEX "elaborati_laboridentity_workspace_id_a651472a" ON "elaborati_laboridentity" ("workspace_id");
ALTER TABLE "elaborati_laborregister" ADD CONSTRAINT "elaborati_laborregis_created_by_id_dea4cf0e_fk_workspace" FOREIGN KEY ("created_by_id") REFERENCES "workspaces_profile" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laborregister" ADD CONSTRAINT "elaborati_laborregis_project_id_83b4131a_fk_projects_" FOREIGN KEY ("project_id") REFERENCES "projects_project" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laborregister" ADD CONSTRAINT "elaborati_laborregis_workspace_id_e683793b_fk_workspace" FOREIGN KEY ("workspace_id") REFERENCES "workspaces_workspace" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "elaborati_laborregister_created_by_id_dea4cf0e" ON "elaborati_laborregister" ("created_by_id");
CREATE INDEX "elaborati_laborregister_project_id_83b4131a" ON "elaborati_laborregister" ("project_id");
CREATE INDEX "elaborati_laborregister_workspace_id_e683793b" ON "elaborati_laborregister" ("workspace_id");
ALTER TABLE "elaborati_laborrevision" ADD CONSTRAINT "elaborati_laborrevis_actor_id_f5c89bf6_fk_workspace" FOREIGN KEY ("actor_id") REFERENCES "workspaces_profile" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laborrevision" ADD CONSTRAINT "elaborati_laborrevis_register_id_02ca1e86_fk_elaborati" FOREIGN KEY ("register_id") REFERENCES "elaborati_laborregister" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "elaborati_laborrevision_actor_id_f5c89bf6" ON "elaborati_laborrevision" ("actor_id");
CREATE INDEX "elaborati_laborrevision_register_id_02ca1e86" ON "elaborati_laborrevision" ("register_id");
ALTER TABLE "elaborati_laboroperation" ADD CONSTRAINT "elaborati_laboropera_identity_id_3ba85973_fk_elaborati" FOREIGN KEY ("identity_id") REFERENCES "elaborati_laboridentity" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laboroperation" ADD CONSTRAINT "elaborati_laboropera_workspace_id_3825df67_fk_workspace" FOREIGN KEY ("workspace_id") REFERENCES "workspaces_workspace" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laboroperation" ADD CONSTRAINT "elaborati_laboropera_register_id_a5388f45_fk_elaborati" FOREIGN KEY ("register_id") REFERENCES "elaborati_laborregister" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laboroperation" ADD CONSTRAINT "elaborati_laboropera_revision_id_7a68d656_fk_elaborati" FOREIGN KEY ("revision_id") REFERENCES "elaborati_laborrevision" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "elaborati_laboroperation_identity_id_3ba85973" ON "elaborati_laboroperation" ("identity_id");
CREATE INDEX "elaborati_laboroperation_workspace_id_3825df67" ON "elaborati_laboroperation" ("workspace_id");
CREATE INDEX "elaborati_laboroperation_register_id_a5388f45" ON "elaborati_laboroperation" ("register_id");
CREATE INDEX "elaborati_laboroperation_revision_id_7a68d656" ON "elaborati_laboroperation" ("revision_id");
 ELSIF existing<>4 THEN
  RAISE EXCEPTION 'Incomplete labor schema; no data modified';
 END IF;
 FOR item IN SELECT * FROM (VALUES ('elaborati_laboridentity','id','uuid',true),
('elaborati_laboridentity','workspace_id','bigint',true),
('elaborati_laboridentity','kind','character varying(8)',true),
('elaborati_laboridentity','name','character varying(200)',true),
('elaborati_laboridentity','external_reference','character varying(100)',true),
('elaborati_laboridentity','profile_id','bigint',false),
('elaborati_laboridentity','basis','character varying(16)',true),
('elaborati_laboridentity','active','boolean',true),
('elaborati_laboridentity','created_by_id','bigint',false),
('elaborati_laboridentity','created_at','timestamp with time zone',true),
('elaborati_laboridentity','updated_at','timestamp with time zone',true),
('elaborati_laborregister','id','uuid',true),
('elaborati_laborregister','workspace_id','bigint',true),
('elaborati_laborregister','project_id','bigint',true),
('elaborati_laborregister','created_by_id','bigint',false),
('elaborati_laborregister','current_version','integer',true),
('elaborati_laborregister','effective_version','integer',false),
('elaborati_laborregister','created_at','timestamp with time zone',true),
('elaborati_laborregister','updated_at','timestamp with time zone',true),
('elaborati_laborrevision','id','uuid',true),
('elaborati_laborrevision','register_id','uuid',true),
('elaborati_laborrevision','number','integer',true),
('elaborati_laborrevision','state','character varying(16)',true),
('elaborati_laborrevision','work_date','date',true),
('elaborati_laborrevision','timezone','character varying(100)',true),
('elaborati_laborrevision','data','jsonb',true),
('elaborati_laborrevision','content_hash','character varying(64)',true),
('elaborati_laborrevision','actor_id','bigint',false),
('elaborati_laborrevision','actor_snapshot','jsonb',true),
('elaborati_laborrevision','action','character varying(16)',true),
('elaborati_laborrevision','reason','character varying(1000)',true),
('elaborati_laborrevision','review_mode','character varying(16)',true),
('elaborati_laborrevision','replaces_version','integer',false),
('elaborati_laborrevision','created_at','timestamp with time zone',true),
('elaborati_laboroperation','id','uuid',true),
('elaborati_laboroperation','workspace_id','bigint',true),
('elaborati_laboroperation','actor_key','bigint',true),
('elaborati_laboroperation','command_id','uuid',true),
('elaborati_laboroperation','request_hash','character varying(64)',true),
('elaborati_laboroperation','register_id','uuid',false),
('elaborati_laboroperation','revision_id','uuid',false),
('elaborati_laboroperation','identity_id','uuid',false),
('elaborati_laboroperation','created_at','timestamp with time zone',true)) x(table_name,column_name,type_name,required) LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_class t ON t.oid=a.attrelid
   JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public'
   AND t.relname=item.table_name AND t.relkind='r' AND NOT t.relrowsecurity
   AND a.attname=item.column_name AND NOT a.attisdropped
   AND format_type(a.atttypid,a.atttypmod)=item.type_name AND a.attnotnull=item.required) THEN
   RAISE EXCEPTION 'Incompatible labor column %.%',item.table_name,item.column_name;
  END IF;
 END LOOP;
 FOR item IN SELECT * FROM (VALUES ('elaborati_laboridentity','workspace_id','workspaces_workspace','id'),
('elaborati_laboridentity','profile_id','workspaces_profile','id'),
('elaborati_laboridentity','created_by_id','workspaces_profile','id'),
('elaborati_laborregister','workspace_id','workspaces_workspace','id'),
('elaborati_laborregister','project_id','projects_project','id'),
('elaborati_laborregister','created_by_id','workspaces_profile','id'),
('elaborati_laborrevision','register_id','elaborati_laborregister','id'),
('elaborati_laborrevision','actor_id','workspaces_profile','id'),
('elaborati_laboroperation','workspace_id','workspaces_workspace','id'),
('elaborati_laboroperation','register_id','elaborati_laborregister','id'),
('elaborati_laboroperation','revision_id','elaborati_laborrevision','id'),
('elaborati_laboroperation','identity_id','elaborati_laboridentity','id')) x(table_name,column_name,target_table,target_column) LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_attribute a
    ON a.attrelid=k.conrelid AND k.conkey=ARRAY[a.attnum]::smallint[]
    JOIN pg_attribute b ON b.attrelid=k.confrelid AND k.confkey=ARRAY[b.attnum]::smallint[]
    WHERE k.contype='f' AND k.conrelid=to_regclass('public.'||item.table_name)
    AND k.confrelid=to_regclass('public.'||item.target_table)
    AND a.attname=item.column_name AND b.attname=item.target_column AND k.convalidated
    AND k.condeferrable AND k.condeferred) THEN
   RAISE EXCEPTION 'Incompatible labor reference %.%',item.table_name,item.column_name;
  END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='elaborati_laborrevision'::regclass
   AND conname='labor_revision_number_uq' AND contype='u' AND convalidated)
 OR NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='elaborati_laboroperation'::regclass
   AND conname='labor_operation_idempotency' AND contype='u' AND convalidated) THEN
  RAISE EXCEPTION 'Missing labor uniqueness contracts';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='elaborati_laborregister'::regclass AND conname='labor_head_revision_fk') THEN
  ALTER TABLE elaborati_laborregister ADD CONSTRAINT labor_head_revision_fk
   FOREIGN KEY(id,current_version) REFERENCES elaborati_laborrevision(register_id,number)
   DEFERRABLE INITIALLY DEFERRED;
  ALTER TABLE elaborati_laborregister ADD CONSTRAINT labor_effective_revision_fk
   FOREIGN KEY(id,effective_version) REFERENCES elaborati_laborrevision(register_id,number)
   DEFERRABLE INITIALLY DEFERRED;
 END IF;
END
$labor$;

CREATE OR REPLACE FUNCTION public.labor_revision_immutable_v1() RETURNS trigger LANGUAGE plpgsql AS $guard$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Labor revision history is immutable'; END IF;
 IF NEW.actor_id IS NULL AND OLD.actor_id IS NOT NULL
   AND (to_jsonb(NEW)-'actor_id')=(to_jsonb(OLD)-'actor_id') THEN RETURN NEW; END IF;
 IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN RAISE EXCEPTION 'Labor revision history is immutable'; END IF;
 RETURN NEW;
END
$guard$;
CREATE OR REPLACE FUNCTION public.labor_operation_immutable_v1() RETURNS trigger LANGUAGE plpgsql AS $guard$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Labor operation receipts are immutable'; END IF;
 IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN RAISE EXCEPTION 'Labor operation receipts are immutable'; END IF;
 RETURN NEW;
END
$guard$;
CREATE OR REPLACE FUNCTION public.labor_register_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $guard$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Labor register history must be preserved'; END IF;
 IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id OR NEW.project_id IS DISTINCT FROM OLD.project_id
   OR NEW.created_at IS DISTINCT FROM OLD.created_at
   OR (NEW.created_by_id IS DISTINCT FROM OLD.created_by_id AND NEW.created_by_id IS NOT NULL)
   OR NEW.current_version<OLD.current_version OR NEW.current_version>OLD.current_version+1 THEN
  RAISE EXCEPTION 'Invalid labor register scope or version change';
 END IF;
 IF NEW.effective_version IS DISTINCT FROM OLD.effective_version THEN
  IF NEW.current_version=OLD.current_version OR NEW.effective_version IS DISTINCT FROM NEW.current_version
    OR NOT EXISTS(SELECT 1 FROM elaborati_laborrevision r WHERE r.register_id=NEW.id
       AND r.number=NEW.current_version AND r.state='approved') THEN
   RAISE EXCEPTION 'Only an appended approved revision may replace effective labor data';
  END IF;
 END IF;
 RETURN NEW;
END
$guard$;
DO $guards$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='elaborati_laborrevision'::regclass AND tgname='labor_revision_immutable') THEN
  CREATE TRIGGER labor_revision_immutable BEFORE UPDATE OR DELETE ON elaborati_laborrevision
   FOR EACH ROW EXECUTE FUNCTION public.labor_revision_immutable_v1();
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='elaborati_laboroperation'::regclass AND tgname='labor_operation_immutable') THEN
  CREATE TRIGGER labor_operation_immutable BEFORE UPDATE OR DELETE ON elaborati_laboroperation
   FOR EACH ROW EXECUTE FUNCTION public.labor_operation_immutable_v1();
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='elaborati_laborregister'::regclass AND tgname='labor_register_scope_guard') THEN
  CREATE TRIGGER labor_register_scope_guard BEFORE UPDATE OR DELETE ON elaborati_laborregister
   FOR EACH ROW EXECUTE FUNCTION public.labor_register_guard_v1();
 END IF;
END
$guards$;
