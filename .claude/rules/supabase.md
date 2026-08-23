---
paths: ["supabase/**", "src/integrations/supabase/**", "src/lib/supabase*"]
---
# Supabase rules
- Migrations are append-only files under `supabase/migrations/`; never edit an existing one, never change schema in a dashboard. After any migration change regenerate types: `npx supabase gen types typescript --project-id $SUPABASE_PROJECT_REF --schema public > src/types/database.ts` and commit the result.
- Every table has RLS enabled with a policy per allowed operation, scoped to the owner or tenant. No `using (true)` outside intentionally public reads.
- `service_role` only in edge functions. Clients use the publishable/anon key.
- Edge functions validate input, return shaped errors (no stack traces), set CORS explicitly, and read secrets from `Deno.env.get`, never from code.
- Local development and tests point at the work-branch database or `supabase start`; never at production.
