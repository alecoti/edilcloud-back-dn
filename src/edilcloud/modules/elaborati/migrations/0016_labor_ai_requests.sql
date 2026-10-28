-- Private, source-backed labor AI requests. Shared Django/SQLx adoption.
SET LOCAL search_path TO public;
DO $labor_ai$
DECLARE item record;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('edilcloud:labor-register-v1',0));
 IF to_regclass('public.elaborati_laborairequest') IS NULL THEN
 --
-- Create model LaborAIRequest
--
CREATE TABLE "elaborati_laborairequest" ("id" uuid NOT NULL PRIMARY KEY, "actor_key" bigint NOT NULL, "command_id" uuid NOT NULL, "request_hash" varchar(64) NOT NULL, "request" jsonb NOT NULL, "state" varchar(16) NOT NULL, "result" jsonb NOT NULL, "model" varchar(64) NOT NULL, "response_id" varchar(128) NULL UNIQUE, "input_tokens" integer NULL CHECK ("input_tokens" >= 0), "output_tokens" integer NULL CHECK ("output_tokens" >= 0), "total_tokens" integer NULL CHECK ("total_tokens" >= 0), "reserved_tokens" integer NOT NULL CHECK ("reserved_tokens" >= 0), "error_code" varchar(64) NOT NULL, "created_at" timestamp with time zone NOT NULL, "updated_at" timestamp with time zone NOT NULL, "project_id" bigint NOT NULL, "workspace_id" bigint NOT NULL, CONSTRAINT "labor_ai_request_command_uq" UNIQUE ("workspace_id", "actor_key", "command_id"), CONSTRAINT "labor_ai_request_state_ck" CHECK ("state" IN ('prepared', 'sent', 'completed', 'failed', 'unknown')));
ALTER TABLE "elaborati_laborairequest" ADD CONSTRAINT "elaborati_laboraireq_project_id_be26507a_fk_projects_" FOREIGN KEY ("project_id") REFERENCES "projects_project" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laborairequest" ADD CONSTRAINT "elaborati_laboraireq_workspace_id_bac017af_fk_workspace" FOREIGN KEY ("workspace_id") REFERENCES "workspaces_workspace" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "elaborati_laborairequest_response_id_8c3c519b_like" ON "elaborati_laborairequest" ("response_id" varchar_pattern_ops);
CREATE INDEX "elaborati_laborairequest_project_id_be26507a" ON "elaborati_laborairequest" ("project_id");
CREATE INDEX "elaborati_laborairequest_workspace_id_bac017af" ON "elaborati_laborairequest" ("workspace_id");
CREATE INDEX "labor_ai_workspace_time_idx" ON "elaborati_laborairequest" ("workspace_id", "created_at");
 END IF;
 FOR item IN SELECT * FROM (VALUES ('id','uuid',true),
('workspace_id','bigint',true),
('project_id','bigint',true),
('actor_key','bigint',true),
('command_id','uuid',true),
('request_hash','character varying(64)',true),
('request','jsonb',true),
('state','character varying(16)',true),
('result','jsonb',true),
('model','character varying(64)',true),
('response_id','character varying(128)',false),
('input_tokens','integer',false),
('output_tokens','integer',false),
('total_tokens','integer',false),
('reserved_tokens','integer',true),
('error_code','character varying(64)',true),
('created_at','timestamp with time zone',true),
('updated_at','timestamp with time zone',true)) x(column_name,type_name,required) LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid='elaborati_laborairequest'::regclass
   AND a.attname=item.column_name AND NOT a.attisdropped AND a.attnotnull=item.required
   AND format_type(a.atttypid,a.atttypmod)=item.type_name) THEN
   RAISE EXCEPTION 'Incompatible labor AI column %',item.column_name;
  END IF;
 END LOOP;
END
$labor_ai$;
CREATE OR REPLACE FUNCTION public.labor_ai_evidence_v1() RETURNS trigger LANGUAGE plpgsql AS $guard$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Labor AI evidence cannot be deleted'; END IF;
 IF ROW(OLD.id,OLD.workspace_id,OLD.project_id,OLD.actor_key,OLD.command_id,OLD.request_hash,OLD.request,OLD.model,OLD.created_at)
   IS DISTINCT FROM ROW(NEW.id,NEW.workspace_id,NEW.project_id,NEW.actor_key,NEW.command_id,NEW.request_hash,NEW.request,NEW.model,NEW.created_at)
   OR OLD.state IN ('completed','failed') AND ROW(OLD.state,OLD.result,OLD.response_id,OLD.input_tokens,OLD.output_tokens,OLD.total_tokens,OLD.reserved_tokens,OLD.error_code)
      IS DISTINCT FROM ROW(NEW.state,NEW.result,NEW.response_id,NEW.input_tokens,NEW.output_tokens,NEW.total_tokens,NEW.reserved_tokens,NEW.error_code) THEN
  RAISE EXCEPTION 'Labor AI source and terminal evidence are immutable';
 END IF;
 RETURN NEW;
END
$guard$;
DO $trigger$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='elaborati_laborairequest'::regclass AND tgname='labor_ai_evidence_guard') THEN
  CREATE TRIGGER labor_ai_evidence_guard BEFORE UPDATE OR DELETE ON elaborati_laborairequest
   FOR EACH ROW EXECUTE FUNCTION public.labor_ai_evidence_v1();
 END IF;
END
$trigger$;
