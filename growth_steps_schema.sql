-- ══════════════════════════════════════════════════════════════
-- GROWTH STEPS — COMPLETE SUPABASE SCHEMA (single source of truth)
-- Paste this ENTIRE file into Supabase → SQL Editor → New query → Run.
-- Safe to re-run any time — it wipes and rebuilds everything below.
-- ══════════════════════════════════════════════════════════════

-- ── 0. CLEAN SLATE ───────────────────────────────────────────
drop table if exists progress_logs cascade;
drop table if exists employee_requests cascade;
drop table if exists calendar_events cascade;
drop table if exists profiles cascade;
drop function if exists handle_new_user cascade;
drop function if exists is_admin cascade;

-- ── 1. PROFILES ── one row per auth.users account ────────────
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null,
  role text not null check (role in ('admin', 'employee', 'student')) default 'student',
  created_at timestamptz default now()
);

-- ── 2. CALENDAR EVENTS ────────────────────────────────────────
create table calendar_events (
  id uuid primary key default gen_random_uuid(),
  event_date date not null unique,
  color text not null default '#6366F1',
  note text default '',
  created_by uuid references profiles(id),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- ── 3. REQUESTS ("needs") ─────────────────────────────────────
create table employee_requests (
  id uuid primary key default gen_random_uuid(),
  employee_id uuid not null references profiles(id) on delete cascade,
  title text not null,
  description text not null,
  status text not null check (status in ('pending', 'approved', 'rejected')) default 'pending',
  admin_note text default '',
  created_at timestamptz default now(),
  reviewed_at timestamptz,
  reviewed_by uuid references profiles(id)
);

-- ── 4. DAILY PROGRESS LOGS ────────────────────────────────────
create table progress_logs (
  id uuid primary key default gen_random_uuid(),
  employee_id uuid not null references profiles(id) on delete cascade,
  log_date date not null,
  summary text not null,
  created_at timestamptz default now(),
  unique (employee_id, log_date)
);

-- ── 5. HELPER: is the current user an admin? ─────────────────
create or replace function is_admin()
returns boolean
language sql
security definer
stable
as $$
  select exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  );
$$;

-- ── 6. AUTO-CREATE PROFILE ON SIGNUP (new users only) ─────────
create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
as $$
begin
  insert into public.profiles (id, full_name, role)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', new.email), 'student')
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- ── 7. BACKFILL: create profiles for any auth.users that       
--      already existed before this schema ran ───────────────
insert into profiles (id, full_name, role)
select id, coalesce(raw_user_meta_data->>'full_name', email), 'student'
from auth.users
on conflict (id) do nothing;

-- ── 8. ROW LEVEL SECURITY ──────────────────────────────────────
alter table profiles enable row level security;
alter table calendar_events enable row level security;
alter table employee_requests enable row level security;
alter table progress_logs enable row level security;

create policy "profiles_select_own_or_admin" on profiles
  for select using (id = auth.uid() or is_admin());

create policy "profiles_update_own" on profiles
  for update using (id = auth.uid());

create policy "calendar_select_all" on calendar_events
  for select using (true);

create policy "calendar_insert_admin_only" on calendar_events
  for insert with check (is_admin());

create policy "calendar_update_admin_only" on calendar_events
  for update using (is_admin());

create policy "calendar_delete_admin_only" on calendar_events
  for delete using (is_admin());

create policy "requests_select_own_or_admin" on employee_requests
  for select using (employee_id = auth.uid() or is_admin());

create policy "requests_insert_own" on employee_requests
  for insert with check (employee_id = auth.uid());

create policy "requests_update_admin_only" on employee_requests
  for update using (is_admin());

create policy "progress_select_own_or_admin" on progress_logs
  for select using (employee_id = auth.uid() or is_admin());

create policy "progress_insert_own" on progress_logs
  for insert with check (employee_id = auth.uid());

create policy "progress_update_own" on progress_logs
  for update using (employee_id = auth.uid());

-- ── 9. MAKE YOUR ADMIN ACCOUNT ─────────────────────────────────
update profiles
set role = 'admin', full_name = 'Vijay'
where id = '0ec33b12-8d5e-4f8e-9ae8-6eef931fa1c8';

update profiles
set role = 'admin'
where id = (select id from auth.users where email = 'rsvijaysarathi123@gmail.com');

-- ── 10. VERIFY ──────────────────────────────────────────────────
-- select u.email, p.full_name, p.role from auth.users u join profiles p on p.id = u.id;
