-- Organization attribution, not an authorization shortcut. Existing documents stay unassigned.
-- Identical in Django and SQLx; immutable published migration files are untouched.
DO $ownership$
DECLARE
    t regclass;
    item record;
    col smallint;
    refcol smallint;
    f oid;
    guard_body text := '
BEGIN
    IF NEW.document_id IS DISTINCT FROM OLD.document_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.assigned_at IS DISTINCT FROM OLD.assigned_at
       OR NEW.basis IS DISTINCT FROM OLD.basis
       OR NEW.assignment_snapshot IS DISTINCT FROM OLD.assignment_snapshot THEN
        RAISE EXCEPTION ''Elaborati ownership is immutable; an explicit reviewed transfer is required'';
    END IF;
    RETURN NEW;
END
';
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('edilcloud:elaborati-ownership-v1',0));
    IF to_regclass('public.elaborati_elaboratoownership') IS NULL THEN
        CREATE TABLE public.elaborati_elaboratoownership (
            document_id uuid NOT NULL,
            workspace_id bigint NOT NULL,
            assigned_by_id bigint NULL,
            assigned_at timestamp with time zone NOT NULL,
            basis varchar(32) NOT NULL,
            assignment_snapshot jsonb NOT NULL,
            CONSTRAINT elab_ownership_pk PRIMARY KEY(document_id),
            CONSTRAINT elab_ownership_document_fk FOREIGN KEY(document_id)
                REFERENCES public.elaborati_elaborato(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT elab_ownership_workspace_fk FOREIGN KEY(workspace_id)
                REFERENCES public.workspaces_workspace(id) DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT elab_ownership_assigner_fk FOREIGN KEY(assigned_by_id)
                REFERENCES public.workspaces_profile(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT elab_ownership_basis CHECK (
                basis::text = ANY (ARRAY['creation','author_confirmation','administrative_review']::text[])
            ),
            CONSTRAINT elab_ownership_snapshot CHECK (assignment_snapshot <> '{}'::jsonb),
            CONSTRAINT elab_ownership_snapshot_object CHECK (jsonb_typeof(assignment_snapshot) = 'object')
        );
        CREATE INDEX elab_owned_workspace_idx ON public.elaborati_elaboratoownership(workspace_id);
    END IF;
    t := 'public.elaborati_elaboratoownership'::regclass;
    IF NOT EXISTS(SELECT 1 FROM pg_class WHERE oid=t AND relkind='r' AND NOT relrowsecurity) THEN
        RAISE EXCEPTION 'Incompatible Elaborati ownership relation; no data assigned';
    END IF;
    -- Validate required columns, allowing a later reviewed additive migration.
    FOR item IN SELECT * FROM (VALUES
        ('document_id','uuid',true),('workspace_id','bigint',true),('assigned_by_id','bigint',false),
        ('assigned_at','timestamp with time zone',true),('basis','character varying(32)',true),
        ('assignment_snapshot','jsonb',true)
    ) AS expected(name,type,required) LOOP
        IF NOT EXISTS(SELECT 1 FROM pg_attribute a
            WHERE a.attrelid=t AND a.attname=item.name AND a.attnotnull=item.required
              AND format_type(a.atttypid,a.atttypmod)=item.type AND NOT a.attisdropped
              AND a.attidentity='' AND a.attgenerated=''
              AND NOT EXISTS(SELECT 1 FROM pg_attrdef d WHERE d.adrelid=t AND d.adnum=a.attnum)) THEN
            RAISE EXCEPTION 'Incompatible Elaborati ownership column %; no data assigned',item.name;
        END IF;
    END LOOP;
    SELECT attnum INTO col FROM pg_attribute WHERE attrelid=t AND attname='document_id';
    IF NOT EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_index i ON i.indexrelid=k.conindid
        WHERE k.conrelid=t AND k.contype='p' AND k.conkey=ARRAY[col]::smallint[]
          AND i.indisvalid AND i.indisready AND i.indnatts=1 AND i.indexprs IS NULL AND i.indpred IS NULL) THEN
        RAISE EXCEPTION 'Incompatible Elaborati ownership primary key';
    END IF;
    FOR item IN SELECT * FROM (VALUES
        ('document_id','public.elaborati_elaborato','c'),
        ('workspace_id','public.workspaces_workspace','a'),
        ('assigned_by_id','public.workspaces_profile','n')
    ) AS expected(name,target,deletion) LOOP
        SELECT attnum INTO col FROM pg_attribute WHERE attrelid=t AND attname=item.name;
        SELECT attnum INTO refcol FROM pg_attribute WHERE attrelid=to_regclass(item.target) AND attname='id';
        IF NOT EXISTS(SELECT 1 FROM pg_constraint k
            WHERE k.conrelid=t AND k.contype='f' AND k.conkey=ARRAY[col]::smallint[]
              AND k.confrelid=to_regclass(item.target) AND k.confkey=ARRAY[refcol]::smallint[]
              AND k.confdeltype::text=item.deletion AND k.confupdtype='a'
              AND k.convalidated AND k.condeferrable AND k.condeferred) THEN
            RAISE EXCEPTION 'Incompatible Elaborati ownership reference %',item.name;
        END IF;
    END LOOP;
    FOR item IN SELECT * FROM (VALUES
        ('elab_ownership_basis', 'basis::text=ANYARRAY[''creation''::text,''author_confirmation''::text,''administrative_review''::text]'),
        ('elab_ownership_snapshot', 'assignment_snapshot<>''{}''::jsonb'),
        ('elab_ownership_snapshot_object', 'jsonb_typeofassignment_snapshot=''object''::text')
    ) AS expected(name,expression) LOOP
        IF NOT EXISTS(SELECT 1 FROM pg_constraint k WHERE k.conrelid=t AND k.conname=item.name
            AND k.contype='c' AND k.convalidated AND NOT k.connoinherit
            AND regexp_replace(pg_get_expr(k.conbin,k.conrelid),'[[:space:]()]','','g')=item.expression) THEN
            RAISE EXCEPTION 'Incompatible Elaborati ownership check %',item.name;
        END IF;
    END LOOP;
    SELECT attnum INTO col FROM pg_attribute WHERE attrelid=t AND attname='workspace_id';
    IF NOT EXISTS(SELECT 1 FROM pg_index i JOIN pg_class x ON x.oid=i.indexrelid JOIN pg_am am ON am.oid=x.relam
        WHERE i.indrelid=t AND x.relname='elab_owned_workspace_idx' AND am.amname='btree'
          AND i.indisvalid AND i.indisready AND NOT i.indisunique AND i.indnatts=1 AND i.indnkeyatts=1
          AND i.indkey[0]=col AND i.indoption[0]=0 AND i.indexprs IS NULL AND i.indpred IS NULL) THEN
        RAISE EXCEPTION 'Incompatible Elaborati ownership workspace index';
    END IF;
    f := to_regprocedure('public.elab_ownership_immutable_v1()');
    IF f IS NULL THEN
        EXECUTE format('CREATE FUNCTION public.elab_ownership_immutable_v1() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public AS %L',guard_body);
        f := to_regprocedure('public.elab_ownership_immutable_v1()');
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
        WHERE p.oid=f AND l.lanname='plpgsql' AND NOT p.prosecdef AND NOT p.proretset
          AND p.prorettype='trigger'::regtype AND p.provolatile='v' AND p.prosrc=guard_body
          AND p.proconfig=ARRAY['search_path=pg_catalog, public']) THEN
        RAISE EXCEPTION 'Incompatible Elaborati ownership immutability function';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=t AND tgname='elab_ownership_immutable') THEN
        CREATE TRIGGER elab_ownership_immutable BEFORE UPDATE ON public.elaborati_elaboratoownership
            FOR EACH ROW EXECUTE FUNCTION public.elab_ownership_immutable_v1();
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=t AND tgname='elab_ownership_immutable'
        AND tgfoid=f AND tgtype=19 AND tgenabled='O' AND NOT tgisinternal
        AND tgnargs=0 AND tgqual IS NULL AND tgconstraint=0 AND tgattr=''::int2vector) THEN
        RAISE EXCEPTION 'Incompatible Elaborati ownership immutability trigger';
    END IF;
END
$ownership$;
