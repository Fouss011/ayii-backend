# AYii Pro – Patch Phase 1 (Pompier)

## Contenu
- `db/V20251026__ayii_pro_phase1.sql` : migration (métadonnées + audit)
- `app/services/integrity.py` : HMAC SHA256 de chaque report
- `app/services/cleanup.py` : suppression/archivage > 24h + log d’event
- `app/services/report_hooks.py` : signature post-insert
- `app/routes/admin_cta.py` : endpoints CTA séparés `/cta/*` protégés par `x-admin-token`

## 1) Migration (Supabase Postgres)
```bash
psql "$DATABASE_URL" -f db/V20251026__ayii_pro_phase1.sql
