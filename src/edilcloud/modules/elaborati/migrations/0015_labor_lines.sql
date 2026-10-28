-- Immutable indexed projection of labor revision rows; shared Django/SQLx.
SET LOCAL search_path TO public;
DO $lines$
DECLARE item record;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('edilcloud:labor-register-v1',0));
 IF to_regclass('public.elaborati_laborline') IS NULL THEN
 --
-- Create model LaborLine
--
CREATE TABLE "elaborati_laborline" ("id" uuid NOT NULL PRIMARY KEY, "row_id" uuid NOT NULL, "work_date" date NOT NULL, "minutes" integer NOT NULL CHECK ("minutes" >= 0), "person_minutes" integer NOT NULL CHECK ("person_minutes" >= 0), "started_at" timestamp with time zone NULL, "ended_at" timestamp with time zone NULL, "break_minutes" integer NULL CHECK ("break_minutes" >= 0), "identity_id" uuid NOT NULL, "revision_id" uuid NOT NULL, CONSTRAINT "labor_line_row_uq" UNIQUE ("revision_id", "row_id"), CONSTRAINT "labor_line_quantity_ck" CHECK (("minutes" > 0 AND "person_minutes" > 0)), CONSTRAINT "labor_line_interval_ck" CHECK ((("ended_at" IS NULL AND "started_at" IS NULL) OR ("ended_at" > ("started_at") AND "started_at" IS NOT NULL))));
ALTER TABLE "elaborati_laborline" ADD CONSTRAINT "elaborati_laborline_identity_id_efe8ad00_fk_elaborati" FOREIGN KEY ("identity_id") REFERENCES "elaborati_laboridentity" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "elaborati_laborline" ADD CONSTRAINT "elaborati_laborline_revision_id_652ff829_fk_elaborati" FOREIGN KEY ("revision_id") REFERENCES "elaborati_laborrevision" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "elaborati_laborline_identity_id_efe8ad00" ON "elaborati_laborline" ("identity_id");
CREATE INDEX "elaborati_laborline_revision_id_652ff829" ON "elaborati_laborline" ("revision_id");
CREATE INDEX "labor_line_identity_day_idx" ON "elaborati_laborline" ("identity_id", "work_date");
CREATE INDEX "labor_line_interval_idx" ON "elaborati_laborline" ("identity_id", "started_at", "ended_at");
 END IF;
 FOR item IN SELECT * FROM (VALUES ('id','uuid',true),
('revision_id','uuid',true),
('identity_id','uuid',true),
('row_id','uuid',true),
('work_date','date',true),
('minutes','integer',true),
('person_minutes','integer',true),
('started_at','timestamp with time zone',false),
('ended_at','timestamp with time zone',false),
('break_minutes','integer',false)) x(column_name,type_name,required) LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid='elaborati_laborline'::regclass
   AND a.attname=item.column_name AND NOT a.attisdropped AND a.attnotnull=item.required
   AND format_type(a.atttypid,a.atttypmod)=item.type_name) THEN
   RAISE EXCEPTION 'Incompatible labor line column %',item.column_name;
  END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='elaborati_laborline'::regclass AND tgname='labor_line_immutable') THEN
  CREATE TRIGGER labor_line_immutable BEFORE UPDATE OR DELETE ON elaborati_laborline
   FOR EACH ROW EXECUTE FUNCTION public.labor_operation_immutable_v1();
 END IF;
END
$lines$;
