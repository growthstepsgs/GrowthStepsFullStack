from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, current_app
)
from extensions import supabase, supabase_admin
from utils.cache import cache
from config import LIBRARY_BOOKS_BUCKET, LIBRARY_COVERS_BUCKET

bp = Blueprint("public", __name__)


@bp.route("/")
def home():
    """Public landing page — everyone can view it.
    The login popup (in base.html) handles authentication."""
    return render_template("index.html")


@bp.route("/home")
def landing():
    """Public landing page — still accessible for direct visits."""
    return render_template("index.html")


@bp.route("/verify-certificate", methods=["GET", "POST"])
def verify_certificate():
    result = None
    error = None

    if request.method == "POST":
        code = request.form.get("verification_code", "").strip()

        # Validate verification code
        if not code or not code.isdigit() or len(code) != 10:
            error = "Please enter a valid 10-digit verification code."

        elif not supabase_admin:
            error = "Server configuration error."

        else:
            try:
                client = supabase_admin

                # Single-roundtrip query with PostgREST join
                cert_res = (
                    client.table("certificates")
                    .select(
                        "id, verification_code, file_url, generated_at, "
                        "profiles(full_name, username, email, college, gender, avatar_url), "
                        "courses(title, description, duration, trainer_name)"
                    )
                    .eq("verification_code", code)
                    .execute()
                )

                if not cert_res.data:
                    error = "No certificate found with that verification code."
                else:
                    cert = cert_res.data[0]
                    profile = cert.get("profiles") or {}
                    course = cert.get("courses") or {}

                    result = {
                        "id": cert.get("id"),
                        "verification_code": cert.get("verification_code"),
                        "file_url": cert.get("file_url"),
                        "generated_at": cert.get("generated_at"),
                        "profiles": profile,
                        "courses": course,
                    }

            except Exception as exc:
                # Fallback to individual queries if relationship syntax encounters schema cache mismatch
                try:
                    client = supabase_admin
                    cert_fallback = client.table("certificates").select("*").eq("verification_code", code).execute()
                    if cert_fallback.data:
                        cert = cert_fallback.data[0]
                        profile = {}
                        course = {}
                        if cert.get("student_id"):
                            prof_r = client.table("profiles").select("full_name, username, email, college, gender, avatar_url").eq("id", cert["student_id"]).single().execute()
                            profile = prof_r.data or {}
                        if cert.get("course_id"):
                            crs_r = client.table("courses").select("title, description, duration, trainer_name").eq("id", cert["course_id"]).single().execute()
                            course = crs_r.data or {}
                        result = {
                            "id": cert.get("id"),
                            "verification_code": cert.get("verification_code"),
                            "file_url": cert.get("file_url"),
                            "generated_at": cert.get("generated_at"),
                            "profiles": profile,
                            "courses": course,
                        }
                    else:
                        error = "No certificate found with that verification code."
                except Exception as fallback_exc:
                    print(f"[VERIFY ERROR] {fallback_exc}")
                    error = "Verification service temporarily unavailable."

    return render_template(
        "shared/verify_certificate.html",
        result=result,
        error=error
    )


@bp.route("/courses")
def courses():
    return render_template("courses/courses.html")


@bp.route("/available-courses")
def available_courses():
    courses = cache.get("available_courses")
    if courses is None:
        courses = []
        client = supabase_admin or supabase
        if client:
            try:
                res = (
                    client.table("courses")
                    .select("*")
                    .eq("is_active", True)
                    .order("created_at", desc=True)
                    .execute()
                )
                courses = res.data or []
                cache.set("available_courses", courses, ttl=300)
            except Exception as exc:
                print(f"courses fetch failed: {exc}")
    return render_template("available_courses.html", courses=courses)


@bp.route("/services")
def services():
    return render_template("services.html")


@bp.route("/workshop")
def workshop():
    return render_template("umm.html")


@bp.route("/google1371138ddddc045a.html")
def google_verify():
    return current_app.send_static_file("google1371138ddddc045a.html")


@bp.route("/gallery")
def gallery():
    photos = cache.get("gallery_photos")
    if photos is None:
        photos = []
        client = supabase_admin or supabase
        if client:
            try:
                res = (
                    client.table("gallery_photos")
                    .select("*")
                    .order("created_at", desc=True)
                    .execute()
                )
                photos = res.data or []
                cache.set("gallery_photos", photos, ttl=300)
            except Exception as exc:
                print(f"gallery fetch failed: {exc}")
                photos = []
    return render_template("gallery.html", photos=photos)


@bp.route("/reviews", methods=["GET", "POST"])
def reviews():
    client = supabase_admin or supabase

    if request.method == "POST":
        user_id = session.get("user_id")
        if not user_id:
            flash("Please log in to submit a review.", "error")
            return redirect(url_for("auth.login"))

        rating = request.form.get("rating", "5")
        content = request.form.get("content", "").strip()

        if not content:
            flash("Review content is required.", "error")
            return redirect(url_for("public.reviews"))

        try:
            rating = int(rating)
            if not (1 <= rating <= 5):
                rating = 5
        except ValueError:
            rating = 5

        user_name = session.get("user_email", "Anonymous")
        if client:
            try:
                prof = (
                    client.table("profiles")
                    .select("full_name")
                    .eq("id", user_id)
                    .single()
                    .execute()
                )
                if prof.data and prof.data.get("full_name"):
                    user_name = prof.data["full_name"]
            except Exception:
                pass

        try:
            client.table("reviews").insert({
                "user_id": user_id,
                "user_name": user_name,
                "rating": rating,
                "content": content,
            }).execute()
            cache.delete("public_reviews")
            flash("Thank you! Your review has been submitted.", "success")
        except Exception as exc:
            flash(f"Could not submit review: {exc}", "error")

        return redirect(url_for("public.reviews"))

    cached = cache.get("public_reviews")
    if cached is not None:
        all_reviews, avg_rating = cached
    else:
        all_reviews = []
        avg_rating = 0.0
        if client:
            try:
                res = (
                    client.table("reviews")
                    .select("*")
                    .order("is_pinned", desc=True)
                    .order("created_at", desc=True)
                    .execute()
                )
                all_reviews = res.data or []
                if all_reviews:
                    avg_rating = round(
                        sum(r["rating"] for r in all_reviews) / len(all_reviews), 1
                    )
                cache.set("public_reviews", (all_reviews, avg_rating), ttl=120)
            except Exception as exc:
                print(f"reviews fetch failed: {exc}")

    return render_template(
        "reviewpage.html",
        reviews=all_reviews,
        avg_rating=avg_rating,
    )


@bp.route("/library")
def library():
    q = request.args.get("q", "").strip()
    selected_tag = request.args.get("tag", "").strip()

    cached_books = cache.get("public_books")
    client = supabase_admin or supabase

    if cached_books is None:
        raw_books = []
        if client:
            try:
                res = (
                    client.table("books")
                    .select("*")
                    .order("uploaded_at", desc=True)
                    .execute()
                )
                raw_books = res.data or []
                cache.set("public_books", raw_books, ttl=120)
            except Exception as exc:
                print(f"[LIBRARY FETCH ERROR] {exc}")
                raw_books = []
        cached_books = raw_books

    # Extract distinct tags across all books
    all_tags_set = set()
    for b in cached_books:
        raw_t = b.get("tags") or ""
        for tag_item in raw_t.split(","):
            cleaned = tag_item.strip()
            if cleaned:
                all_tags_set.add(cleaned)
    all_tags = sorted(list(all_tags_set), key=lambda s: s.lower())

    # Filter books by query and selected tag
    filtered = []
    for b in cached_books:
        if q:
            match_q = (
                (b.get("title") and q.lower() in b["title"].lower())
                or (b.get("author") and q.lower() in b["author"].lower())
                or (b.get("tags") and q.lower() in b["tags"].lower())
                or (b.get("notes") and q.lower() in b["notes"].lower())
            )
            if not match_q:
                continue

        if selected_tag:
            book_tags = [t.strip().lower() for t in (b.get("tags") or "").split(",") if t.strip()]
            if selected_tag.lower() not in book_tags:
                continue

        book_copy = dict(b)
        book_copy["tag_list"] = [t.strip() for t in (b.get("tags") or "").split(",") if t.strip()]

        if b.get("cover_path") and client:
            try:
                book_copy["cover_url"] = client.storage.from_(LIBRARY_COVERS_BUCKET).get_public_url(b["cover_path"])
            except Exception:
                book_copy["cover_url"] = None
        else:
            book_copy["cover_url"] = None

        filtered.append(book_copy)

    return render_template(
        "library.html",
        books=filtered,
        all_tags=all_tags,
        selected_tag=selected_tag,
        search_query=q,
    )


@bp.route("/library/<book_id>")
def book_detail(book_id):
    client = supabase_admin or supabase
    if not client:
        flash("Library service unavailable.", "error")
        return redirect(url_for("public.library"))

    try:
        res = client.table("books").select("*").eq("id", book_id).single().execute()
        if not res.data:
            flash("Book not found.", "error")
            return redirect(url_for("public.library"))

        book = dict(res.data)
        book["tag_list"] = [t.strip() for t in (book.get("tags") or "").split(",") if t.strip()]
        if book.get("cover_path"):
            try:
                book["cover_url"] = client.storage.from_(LIBRARY_COVERS_BUCKET).get_public_url(book["cover_path"])
            except Exception:
                book["cover_url"] = None
        else:
            book["cover_url"] = None

        return render_template("book_detail.html", book=book)
    except Exception as exc:
        print(f"[BOOK DETAIL ERROR] {exc}")
        flash("Could not retrieve book details.", "error")
        return redirect(url_for("public.library"))


@bp.route("/library/download/<book_id>")
def download_book(book_id):
    client = supabase_admin or supabase
    if not client:
        flash("Storage service unavailable.", "error")
        return redirect(url_for("public.library"))

    try:
        res = client.table("books").select("file_path, title, file_type").eq("id", book_id).single().execute()
        if not res.data or not res.data.get("file_path"):
            flash("Book file not found.", "error")
            return redirect(url_for("public.library"))

        file_path = res.data["file_path"]
        signed_res = client.storage.from_(LIBRARY_BOOKS_BUCKET).create_signed_url(file_path, expires_in=3600)

        signed_url = None
        if hasattr(signed_res, "signedURL") and signed_res.signedURL:
            signed_url = signed_res.signedURL
        elif hasattr(signed_res, "signedUrl") and signed_res.signedUrl:
            signed_url = signed_res.signedUrl
        elif isinstance(signed_res, dict):
            signed_url = signed_res.get("signedURL") or signed_res.get("signedUrl")

        if signed_url:
            return redirect(signed_url)
        else:
            flash("Unable to generate secure download link.", "error")
            return redirect(url_for("public.library"))
    except Exception as exc:
        print(f"[BOOK DOWNLOAD ERROR] {exc}")
        flash(f"Error accessing book file: {exc}", "error")
        return redirect(url_for("public.library"))


@bp.route("/sitemap.xml")
def sitemap():
    pages = [
        {"loc": url_for("public.home", _external=True),              "priority": "1.0",  "changefreq": "weekly"},
        {"loc": url_for("public.courses", _external=True),           "priority": "0.8",  "changefreq": "weekly"},
        {"loc": url_for("public.available_courses", _external=True), "priority": "0.8",  "changefreq": "weekly"},
        {"loc": url_for("public.library", _external=True),           "priority": "0.8",  "changefreq": "weekly"},
        {"loc": url_for("public.services", _external=True),          "priority": "0.8",  "changefreq": "monthly"},
        {"loc": url_for("public.workshop", _external=True),          "priority": "0.7",  "changefreq": "monthly"},
        {"loc": url_for("public.gallery", _external=True),           "priority": "0.7",  "changefreq": "weekly"},
        {"loc": url_for("auth.login", _external=True),               "priority": "0.5",  "changefreq": "yearly"},
        {"loc": url_for("auth.signup", _external=True),              "priority": "0.5",  "changefreq": "yearly"},
    ]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for p in pages:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{p['loc']}</loc>")
        xml_lines.append(f"    <lastmod>{now}</lastmod>")
        xml_lines.append(f"    <changefreq>{p['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{p['priority']}</priority>")
        xml_lines.append("  </url>")
    xml_lines.append("</urlset>")

    return "\n".join(xml_lines), 200, {"Content-Type": "application/xml"}


@bp.route("/robots.txt")
def robots():
    base = request.url_root.rstrip("/")
    lines = [
        "User-agent: *",
        "Disallow: /dashboard/",
        "Disallow: /admin/",
        "Disallow: /login",
        "Disallow: /signup",
        "",
        f"Sitemap: {base}/sitemap.xml",
        "",
    ]
    return "\n".join(lines), 200, {"Content-Type": "text/plain"}


@bp.route("/contact", methods=["POST"])
def contact():
    return redirect(request.referrer or url_for("public.home"))