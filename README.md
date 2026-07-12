# GS-Growth Steps — Flask + Supabase

## File structure
```
gs_flask/
├── app.py                     # all routes / auth logic
├── requirements.txt
├── .env.example                # copy to .env and fill in
├── static/
│   ├── css/styles.css
│   ├── js/script.js
│   └── google1371138ddddc045a.html
└── templates/
    ├── index.html               # (was index.html)      -> "/"
    ├── courses.html              -> "/courses"
    ├── available_courses.html    -> "/available-courses"
    ├── services.html             -> "/services"
    ├── umm.html                  -> "/workshop"
    ├── login.html                -> "/login"
    ├── signup.html                -> "/signup"
    ├── employee_dashboard.html   -> "/dashboard/employee"
    └── admin_dashboard.html      -> "/dashboard/admin"
```

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: SUPABASE_URL, SUPABASE_KEY (anon/public key), SECRET_KEY
flask --app app run --debug
```

## Supabase setup
1. Create a Supabase project. In **Authentication → Providers**, email/password sign-up is enabled by default.
2. Create a `profiles` table:
   ```sql
   create table profiles (
     id uuid primary key references auth.users(id),
     name text,
     email text unique,
     role text default 'employee',
     created_at timestamp with time zone default now()
   );
   alter table profiles enable row level security;
   create policy "allow read for anon" on profiles for select using (true);
   create policy "allow insert for anon" on profiles for insert with check (true);
   ```
   (Tighten these policies later — they're permissive to get you moving quickly.)
3. Put the project URL + anon key in `.env`.

## Auth model
- **Admin**: hardcoded to `rsvijaysarathi123@gmail.com` / the password you gave me, checked directly in `app.py` — no Supabase row needed. Goes to `/dashboard/admin`.
- **Employee**: anyone who signs up via `/signup`. Account is created in Supabase Auth, and a matching row is added to `profiles` with `role = 'employee'`. Goes to `/dashboard/employee`.
- Sessions are Flask server-side sessions (`session['user_email']`, `session['role']`). `login_required` / `admin_required` decorators guard the dashboard routes.

## What didn't change
All existing pages (`index.html`, `courses.html`, `services.html`, `available_courses.html`, `umm.html`) keep their exact HTML/CSS — only the `href="styles.css"`, `src="script.js"`, and internal page links were swapped for Jinja `url_for(...)` calls so Flask's routing/static serving works. No visual/UI changes.

## Next steps you'll likely want
- Move the EmailJS contact-form submission server-side (there's a stub `/contact` POST route ready in `app.py`).
- Add password-reset flow via Supabase Auth.
- Tighten RLS policies on `profiles` once you're past prototyping.
