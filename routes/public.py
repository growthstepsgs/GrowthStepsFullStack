from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, current_app
)
from extensions import supabase, supabase_admin

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

                # 1. Find certificate
                cert_res = (
                    client.table("certificates")
                    .select("*")
                    .eq("verification_code", code)
                    .execute()
                )

                print("[VERIFY] Certificate response:", cert_res.data)

                if not cert_res.data:
                    error = "No certificate found with that verification code."

                else:
                    cert = cert_res.data[0]

                    print("[VERIFY] Certificate:", cert)

                    # 2. Student profile
                    profile = {}

                    student_id = cert.get("student_id")

                    if student_id:
                        try:
                            prof_res = (
                                client.table("profiles")
                                .select(
                                    "full_name, username, email, college, gender, avatar_url"
                                )
                                .eq("id", student_id)
                                .single()
                                .execute()
                            )

                            profile = prof_res.data or {}

                        except Exception as exc:
                            print("[VERIFY] Profile error:", exc)

                    # 3. Course
                    course = {}

                    course_id = cert.get("course_id")

                    if course_id:
                        try:
                            course_res = (
                                client.table("courses")
                                .select(
                                    "title, description, duration, trainer_name"
                                )
                                .eq("id", course_id)
                                .single()
                                .execute()
                            )

                            course = course_res.data or {}

                        except Exception as exc:
                            print("[VERIFY] Course error:", exc)

                    # 4. Build safe result
                    result = {
                        "id": cert.get("id"),
                        "verification_code": cert.get("verification_code"),
                        "file_url": cert.get("file_url"),
                        "generated_at": cert.get("generated_at"),
                        "profiles": profile,
                        "courses": course,
                    }

                    print("[VERIFY] Final result:", result)

            except Exception as exc:
                print("[VERIFY ERROR]", repr(exc))

                import traceback
                traceback.print_exc()

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
            flash("Thank you! Your review has been submitted.", "success")
        except Exception as exc:
            flash(f"Could not submit review: {exc}", "error")

        return redirect(url_for("public.reviews"))

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
        except Exception as exc:
            print(f"reviews fetch failed: {exc}")

    return render_template(
        "reviewpage.html",
        reviews=all_reviews,
        avg_rating=avg_rating,
    )


@bp.route("/sitemap.xml")
def sitemap():
    pages = [
        {"loc": url_for("public.home", _external=True),              "priority": "1.0",  "changefreq": "weekly"},
        {"loc": url_for("public.courses", _external=True),           "priority": "0.8",  "changefreq": "weekly"},
        {"loc": url_for("public.available_courses", _external=True), "priority": "0.8",  "changefreq": "weekly"},
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
