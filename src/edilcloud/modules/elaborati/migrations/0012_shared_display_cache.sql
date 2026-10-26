-- Shared derived cache. Keep historic migration checksums immutable.
-- This file is identical in the Django and native migration packages.
DO $shared_cache$
DECLARE
    item record;
    table_oid regclass;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('edilcloud:shared-display-pdf-v1',0));
    IF to_regclass('public.elaborati_draftpdfcache') IS NULL THEN
        CREATE TABLE public.elaborati_draftpdfcache (
            revision_id uuid NOT NULL,
            profile_id bigint NOT NULL,
            content_hash text NOT NULL,
            pdf_file text NOT NULL,
            pdf_hash text NOT NULL,
            created_at timestamp with time zone NOT NULL,
            PRIMARY KEY (revision_id,profile_id),
            CONSTRAINT elab_display_revision_fk FOREIGN KEY (revision_id)
                REFERENCES public.elaborati_elaboratorevision(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT elab_display_profile_fk FOREIGN KEY (profile_id)
                REFERENCES public.workspaces_profile(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT elab_display_content_nonempty CHECK (NOT (content_hash = '')),
            CONSTRAINT elab_display_file_nonempty CHECK (NOT (pdf_file = '')),
            CONSTRAINT elab_display_hash_nonempty CHECK (NOT (pdf_hash = ''))
        );
        CREATE INDEX elab_display_pdf_file_idx ON public.elaborati_draftpdfcache(pdf_file);
        CREATE INDEX elab_display_profile_idx ON public.elaborati_draftpdfcache(profile_id);
    END IF;
    table_oid := 'public.elaborati_draftpdfcache'::regclass;
    IF NOT EXISTS(SELECT 1 FROM pg_class WHERE oid=table_oid AND relkind='r' AND NOT relrowsecurity)
       OR (SELECT count(*) FROM pg_attribute WHERE attrelid=table_oid AND attnum>0 AND NOT attisdropped)<>6 THEN
        RAISE EXCEPTION 'Incompatible shared Elaborati PDF cache table; no data replaced';
    END IF;
    FOR item IN SELECT * FROM (VALUES
        (1,'revision_id','uuid'),(2,'profile_id','bigint'),(3,'content_hash','text'),
        (4,'pdf_file','text'),(5,'pdf_hash','text'),(6,'created_at','timestamp with time zone')
    ) AS expected(position,name,type) LOOP
        IF NOT EXISTS(SELECT 1 FROM pg_attribute a
            WHERE a.attrelid=table_oid AND a.attnum=item.position AND a.attname=item.name
              AND format_type(a.atttypid,a.atttypmod)=item.type AND a.attnotnull
              AND NOT a.attisdropped AND a.attidentity='' AND a.attgenerated=''
              AND NOT EXISTS(SELECT 1 FROM pg_attrdef d WHERE d.adrelid=table_oid AND d.adnum=a.attnum)) THEN
            RAISE EXCEPTION 'Incompatible shared Elaborati PDF cache column %; no data replaced',item.name;
        END IF;
    END LOOP;
    IF NOT EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_index i ON i.indexrelid=k.conindid
        WHERE k.conrelid=table_oid AND k.contype='p' AND k.conkey=ARRAY[1,2]::smallint[]
          AND i.indisvalid AND i.indnatts=2) THEN
        RAISE EXCEPTION 'Incompatible shared Elaborati PDF cache primary key';
    END IF;
    FOR item IN SELECT * FROM (VALUES (1,'public.elaborati_elaboratorevision'),(2,'public.workspaces_profile'))
        AS expected(position,target) LOOP
        IF NOT EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_attribute a
             ON a.attrelid=k.confrelid AND a.attname='id'
            WHERE k.conrelid=table_oid AND k.contype='f' AND k.conkey=ARRAY[item.position]::smallint[]
              AND k.confrelid=to_regclass(item.target) AND k.confkey=ARRAY[a.attnum]::smallint[]
              AND k.confdeltype='c' AND k.confupdtype='a' AND k.convalidated
              AND k.condeferrable AND k.condeferred) THEN
            RAISE EXCEPTION 'Incompatible shared Elaborati PDF cache relation %',item.target;
        END IF;
    END LOOP;
    FOR item IN SELECT * FROM (VALUES
        ('elab_display_content_nonempty',$e$NOTcontent_hash=''::text$e$),
        ('elab_display_file_nonempty',$e$NOTpdf_file=''::text$e$),
        ('elab_display_hash_nonempty',$e$NOTpdf_hash=''::text$e$)
    ) AS expected(name,expression) LOOP
        IF NOT EXISTS(SELECT 1 FROM pg_constraint k WHERE k.conrelid=table_oid
            AND k.contype='c' AND k.conname=item.name AND k.convalidated AND NOT k.connoinherit
            AND regexp_replace(pg_get_expr(k.conbin,k.conrelid),'[[:space:]()]','','g')=item.expression) THEN
            RAISE EXCEPTION 'Incompatible shared Elaborati PDF cache constraint %',item.name;
        END IF;
    END LOOP;
    FOR item IN SELECT * FROM (VALUES ('elab_display_pdf_file_idx','4'),('elab_display_profile_idx','2'))
        AS expected(name,column_number) LOOP
        IF NOT EXISTS(SELECT 1 FROM pg_index i JOIN pg_class ix ON ix.oid=i.indexrelid
            JOIN pg_am am ON am.oid=ix.relam
            WHERE i.indrelid=table_oid AND ix.relname=item.name AND i.indisvalid
              AND NOT i.indisunique AND i.indnatts=1 AND i.indnkeyatts=1
              AND i.indkey::text=item.column_number AND i.indpred IS NULL
              AND i.indexprs IS NULL AND am.amname='btree') THEN
            RAISE EXCEPTION 'Incompatible shared Elaborati PDF cache index %',item.name;
        END IF;
    END LOOP;
    IF to_regclass('edilcloud_runtime.elaborati_draft_pdf_cache') IS NOT NULL THEN
        LOCK TABLE edilcloud_runtime.elaborati_draft_pdf_cache IN SHARE ROW EXCLUSIVE MODE;
        INSERT INTO public.elaborati_draftpdfcache
            (revision_id,profile_id,content_hash,pdf_file,pdf_hash,created_at)
        SELECT revision_id,profile_id,content_hash,pdf_file,pdf_hash,created_at
            FROM edilcloud_runtime.elaborati_draft_pdf_cache
        ON CONFLICT (revision_id,profile_id) DO UPDATE SET
            content_hash=EXCLUDED.content_hash,pdf_file=EXCLUDED.pdf_file,
            pdf_hash=EXCLUDED.pdf_hash,created_at=EXCLUDED.created_at
        WHERE elaborati_draftpdfcache.created_at<EXCLUDED.created_at;
        DELETE FROM edilcloud_runtime.elaborati_draft_pdf_cache;
    END IF;
END
$shared_cache$;
