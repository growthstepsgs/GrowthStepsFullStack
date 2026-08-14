import uuid
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.utils import secure_filename
from extensions import supabase, supabase_admin
from config import VALID_STATUSES, GALLERY_BUCKET
from utils import admin_required, _allowed_image

bp = Blueprint("admin", __name__)


@bp.route("/dashboard/admin")
@admin_required
def admin_dashboard():
    client = supabase_admin or supabase

    profiles = []
    if client:
        try:
            res = client.table("profiles").select("role").execute()
            profiles = res.data or []
        except Exception:
            pass

    student_count = sum(1 for p in profiles if p.get("role") == "student")
    employee_count = sum(1 for p in profiles if p.get("role") == "employee")
    total_users = len(profiles)

    course_count = 0
    if client:
        try:
            res = client.table("courses").select("*").execute()
            course_count = len(res.data or [])
        except Exception:
            pass

    return render_template(
        "admin/admin_dashboard.html",
        email=session.get("user_email"),
        total_users=total_users,
        course_count=course_count,
        student_count=student_count,
        employee_count=employee_count,
    )


@bp.route("/dashboard/admin/students")
@admin_required
def admin_all_students():
    client = supabase_admin or supabase

    profiles = []
    if client:
        try:
            res = client.table("profiles").select("*").order("created_at", desc=True).execute()
            profiles = res.data or []
        except Exception:
            pass

    courses = {}
    if client:
        try:
            res = client.table("courses").select("id, title").execute()
            for c in (res.data or []):
                courses[c["id"]] = c.get("title", "Untitled")
        except Exception:
            pass

    enrollments = []
    enrollments_by_student = {}
    if client:
        try:
            res = client.table("enrollments").select("*").execute()
            enrollments = res.data or []

            student_ids = list({e["student_id"] for e in enrollments if e.get("student_id")})
            names = {}
            if student_ids:
                r = client.table("profiles").select("id, full_name, email, username").in_("id", student_ids).execute()
                for p in (r.data or []):
                    names[p["id"]] = {
                        "name": p.get("full_name") or p.get("username") or p.get("email") or "Unknown",
                        "email": p.get("email", ""),
                        "username": p.get("username", "")
                    }

            for e in enrollments:
                e["student_name"] = names.get(e.get("student_id"), {}).get("name", "Unknown")
                e["student_email"] = names.get(e.get("student_id"), {}).get("email", "")
                e["course_title"] = courses.get(e.get("course_id"), "Unknown")
                sid = e.get("student_id")
                if sid:
                    enrollments_by_student.setdefault(sid, []).append(e)
        except Exception as exc:
            print(f"admin_all_students enrollments failed: {exc}")

    total_students = len([p for p in profiles if p.get("role") == "student"])
    total_employees = len([p for p in profiles if p.get("role") == "employee"])

    return render_template(
        "admin/all_login_and_enrollment.html",
        email=session.get("user_email"),
        profiles=profiles,
        enrollments_by_student=enrollments_by_student,
        total_students=total_students,
        total_employees=total_employees,
    )


@bp.route("/dashboard/admin/enrollments")
@admin_required
def admin_enrollments():
    client = supabase_admin or supabase
    enrollments = []
    if client:
        try:
            res = client.table("enrollments").select("*").order("created_at", desc=True).execute()
            enrollments = res.data or []

            student_ids = list({e["student_id"] for e in enrollments if e.get("student_id")})
            course_ids = list({e["course_id"] for e in enrollments if e.get("course_id")})

            names = {}
            if student_ids:
                r = client.table("profiles").select("id, full_name, email").in_("id", student_ids).execute()
                for p in (r.data or []):
                    names[p["id"]] = p.get("full_name") or p.get("email") or "Unknown"

            courses = {}
            if course_ids:
                r = client.table("courses").select("id, title").in_("id", course_ids).execute()
                for c in (r.data or []):
                    courses[c["id"]] = c.get("title") or "Untitled"

            for e in enrollments:
                e["student_name"] = names.get(e.get("student_id"), "Unknown")
                e["course_title"] = courses.get(e.get("course_id"), "Unknown")
        except Exception as exc:
            print(f"admin_enrollments failed: {exc}")

    return render_template(
        "admin/admin_enrollments.html",
        email=session.get("user_email"),
        enrollments=enrollments,
    )


@bp.route("/dashboard/admin/all-data")
@admin_required
def admin_all_data():
    client = supabase_admin or supabase
    profiles = []
    if client:
        try:
            res = client.table("profiles").select("*").order("created_at", desc=True).execute()
            profiles = res.data or []
        except Exception:
            pass

    return render_template(
        "admin/all_data.html",
        email=session.get("user_email"),
        profiles=profiles,
    )


@bp.route("/dashboard/admin/users/<user_id>/role", methods=["POST"])
@admin_required
def admin_update_role(user_id):
    new_role = request.form.get("role", "").strip()
    if new_role not in ("student", "employee", "admin"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin.admin_all_students"))

    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin.admin_all_students"))

    try:
        client.table("profiles").update({"role": new_role}).eq("id", user_id).execute()
        flash(f"Role updated to {new_role}.", "success")
    except Exception as exc:
        flash(f"Could not update role: {exc}", "error")

    return redirect(url_for("admin.admin_all_students"))


@bp.route("/dashboard/admin/enrollments/<enrollment_id>/update", methods=["POST"])
@admin_required
def admin_update_enrollment(enrollment_id):
    status = request.form.get("status", "").strip()
    if status not in ("pending", "approved", "rejected"):
        flash("Invalid status.", "error")
        return redirect(url_for("admin.admin_enrollments"))

    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin.admin_enrollments"))

    try:
        update_data = {"status": status}
        if status == "approved":
            update_data["approved_at"] = datetime.now(timezone.utc).isoformat()
        client.table("enrollments").update(update_data).eq("id", enrollment_id).execute()
        flash(f"Enrollment {status}.", "success")
    except Exception as exc:
        flash(f"Could not update enrollment: {exc}", "error")

    return redirect(url_for("admin.admin_enrollments"))


@bp.route("/dashboard/admin/requests")
@admin_required
def admin_requests():
    client = supabase_admin or supabase
    all_requests = []
    if client:
        try:
            req_res = (
                client.table("requests")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
            all_requests = req_res.data or []

            employee_ids = list({r["employee_id"] for r in all_requests if r.get("employee_id")})
            names_by_id = {}
            if employee_ids:
                prof_res = (
                    client.table("profiles")
                    .select("id, full_name")
                    .in_("id", employee_ids)
                    .execute()
                )
                names_by_id = {
                    p["id"]: p.get("full_name") for p in (prof_res.data or [])
                }

            for r in all_requests:
                r["employee_name"] = names_by_id.get(r.get("employee_id")) or "Unknown"
        except Exception as exc:
            print(f"admin_requests fetch failed: {exc}")
            all_requests = []

    return render_template(
        "admin/admin_requests.html",
        email=session.get("user_email"),
        all_requests=all_requests,
    )


@bp.route("/dashboard/admin/requests/<request_id>/update", methods=["POST"])
@admin_required
def admin_update_request(request_id):
    status = request.form.get("status", "").strip()
    admin_note = request.form.get("admin_note", "").strip()

    if status not in VALID_STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("admin.admin_requests"))

    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured on the server.", "error")
        return redirect(url_for("admin.admin_requests"))

    try:
        client.table("requests").update({
            "status": status,
            "admin_note": admin_note,
        }).eq("id", request_id).execute()
        flash("Request updated.", "success")
    except Exception as exc:
        flash(f"Could not update request: {exc}", "error")

    return redirect(url_for("admin.admin_requests"))


@bp.route("/dashboard/admin/progress")
@admin_required
def admin_progress():
    client = supabase_admin or supabase
    all_progress = []
    if client:
        try:
            res = (
                client.table("daily_progress")
                .select("*")
                .order("work_date", desc=True)
                .limit(200)
                .execute()
            )
            all_progress = res.data or []
            emp_ids = list({p["employee_id"] for p in all_progress if p.get("employee_id")})
            names = {}
            if emp_ids:
                prof = client.table("profiles").select("id, full_name, email").in_("id", emp_ids).execute()
                for p in (prof.data or []):
                    names[p["id"]] = p.get("full_name") or p.get("email") or "Unknown"
            for p in all_progress:
                p["employee_name"] = names.get(p.get("employee_id"), "Unknown")
        except Exception as exc:
            print(f"admin progress fetch failed: {exc}")
    return render_template("admin/admin_progress.html", email=session.get("user_email"), all_progress=all_progress)


@bp.route("/admin/admin_gallery", methods=["GET", "POST"])
@admin_required
def admin_gallery():
    client = supabase_admin or supabase

    if request.method == "POST":
        caption = request.form.get("caption", "").strip()
        file = request.files.get("image")

        if not file or file.filename == "":
            flash("Please choose an image to upload.", "error")
            return redirect(url_for("admin.admin_gallery"))

        if not _allowed_image(file.filename):
            flash("Unsupported file type — use jpg, png, webp, or gif.", "error")
            return redirect(url_for("admin.admin_gallery"))

        if not client:
            flash("Supabase isn't configured on the server.", "error")
            return redirect(url_for("admin.admin_gallery"))

        ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
        storage_path = f"{uuid.uuid4().hex}.{ext}"

        try:
            file_bytes = file.read()
            client.storage.from_(GALLERY_BUCKET).upload(
                storage_path,
                file_bytes,
                {"content-type": file.mimetype},
            )
            public_url = client.storage.from_(GALLERY_BUCKET).get_public_url(storage_path)

            client.table("gallery_photos").insert({
                "image_url": public_url,
                "storage_path": storage_path,
                "caption": caption,
            }).execute()

            flash("Photo uploaded.", "success")
        except Exception as exc:
            flash(f"Upload failed: {exc}", "error")

        return redirect(url_for("admin.admin_gallery"))

    photos = []
    if client:
        try:
            res = (
                client.table("gallery_photos")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
            photos = res.data or []
        except Exception:
            photos = []

    return render_template("admin/admin_gallery.html", photos=photos)


@bp.route("/admin/courses", methods=["GET", "POST"])
@admin_required
def admin_courses():
    client = supabase_admin or supabase

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "0").strip()
        original_price = request.form.get("original_price", "").strip()
        duration = request.form.get("duration", "").strip()
        schedule = request.form.get("schedule", "").strip()
        mode = request.form.get("mode", "").strip()
        status = request.form.get("status", "coming_soon")
        tags_raw = request.form.get("tags", "").strip()
        cta_link = request.form.get("cta_link", "").strip()
        cta_label = request.form.get("cta_label", "View Course Details").strip()

        if not title:
            flash("Course title is required.", "error")
            return redirect(url_for("admin.admin_courses"))

        try:
            payload = {
                "title": title,
                "description": description,
                "price": int(price) if price else 0,
                "duration": duration,
                "schedule": schedule,
                "mode": mode,
                "status": status,
                "tags": [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else [],
                "cta_link": cta_link,
                "cta_label": cta_label,
            }
            if original_price:
                payload["original_price"] = int(original_price)

            client.table("courses").insert(payload).execute()
            flash("Course published successfully.", "success")
        except Exception as exc:
            flash(f"Failed to publish course: {exc}", "error")
        return redirect(url_for("admin.admin_courses"))

    courses = []
    if client:
        try:
            res = client.table("courses").select("*").order("created_at", desc=True).execute()
            courses = res.data or []
        except Exception:
            courses = []
    return render_template("admin/admin_courses.html", courses=courses)


@bp.route("/admin/courses/<course_id>/delete", methods=["POST"])
@admin_required
def admin_delete_course(course_id):
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin.admin_courses"))
    try:
        client.table("courses").delete().eq("id", course_id).execute()
        flash("Course deleted.", "success")
    except Exception as exc:
        flash(f"Could not delete course: {exc}", "error")
    return redirect(url_for("admin.admin_courses"))


@bp.route("/dashboard/admin/gallery/<photo_id>/delete", methods=["POST"])
@admin_required
def admin_delete_gallery_photo(photo_id):
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured on the server.", "error")
        return redirect(url_for("admin.admin_gallery"))

    try:
        row = (
            client.table("gallery_photos")
            .select("storage_path")
            .eq("id", photo_id)
            .single()
            .execute()
        )
        if row.data:
            client.storage.from_(GALLERY_BUCKET).remove([row.data["storage_path"]])
        client.table("gallery_photos").delete().eq("id", photo_id).execute()
        flash("Photo deleted.", "success")
    except Exception as exc:
        flash(f"Could not delete photo: {exc}", "error")

    return redirect(url_for("admin.admin_gallery"))


@bp.route("/admin/cleanup-orphaned-photos")
@admin_required
def cleanup_orphaned_photos():
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin.admin_gallery"))

    deleted = 0
    try:
        res = client.table("gallery_photos").select("*").execute()
        for p in (res.data or []):
            try:
                client.storage.from_(GALLERY_BUCKET).download(p["storage_path"])
            except Exception:
                client.table("gallery_photos").delete().eq("id", p["id"]).execute()
                deleted += 1
    except Exception as exc:
        flash(f"Cleanup failed: {exc}", "error")
        return redirect(url_for("admin.admin_gallery"))

    flash(f"Cleanup done — removed {deleted} orphaned row(s).", "success")
    return redirect(url_for("admin.admin_gallery"))


@bp.route("/admin/course-contents", methods=["GET", "POST"])
@admin_required
def admin_course_contents():
    client = supabase_admin or supabase
    courses = []
    contents = []

    if client:
        try:
            res = client.table("courses").select("id, title").order("title").execute()
            courses = res.data or []
        except Exception:
            pass

        try:
            res = client.table("course_contents").select("*, courses(title)").order("sort_order").execute()
            contents = res.data or []
        except Exception:
            pass

    if request.method == "POST":
        course_id = request.form.get("course_id", "").strip()
        title = request.form.get("title", "").strip()
        content_type = request.form.get("type", "").strip()
        url = request.form.get("url", "").strip()
        sort_order = request.form.get("sort_order", "0").strip()

        if not course_id or not title or not content_type or not url:
            flash("Please fill in all fields.", "error")
            return redirect(url_for("admin.admin_course_contents"))

        if content_type not in ("video", "ppt", "assignment", "certificate"):
            flash("Invalid content type.", "error")
            return redirect(url_for("admin.admin_course_contents"))

        try:
            client.table("course_contents").insert({
                "course_id": course_id,
                "title": title,
                "type": content_type,
                "url": url,
                "sort_order": int(sort_order) if sort_order else 0,
            }).execute()
            flash("Content added successfully.", "success")
        except Exception as exc:
            flash(f"Failed to add content: {exc}", "error")

        return redirect(url_for("admin.admin_course_contents"))

    return render_template(
        "admin/admin_course_contents.html",
        email=session.get("user_email"),
        courses=courses,
        contents=contents,
    )


@bp.route("/admin/course-contents/<content_id>/delete", methods=["POST"])
@admin_required
def admin_delete_content(content_id):
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin.admin_course_contents"))

    try:
        client.table("course_contents").delete().eq("id", content_id).execute()
        flash("Content deleted.", "success")
    except Exception as exc:
        flash(f"Could not delete content: {exc}", "error")

    return redirect(url_for("admin.admin_course_contents"))


@bp.route("/reviews/<review_id>/pin", methods=["POST"])
@admin_required
def admin_pin_review(review_id):
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("public.reviews"))

    is_pinned = request.form.get("is_pinned") == "true"
    try:
        client.table("reviews").update({
            "is_pinned": is_pinned
        }).eq("id", review_id).execute()
        flash("Review updated.", "success")
    except Exception as exc:
        flash(f"Could not update review: {exc}", "error")

    return redirect(url_for("public.reviews"))


@bp.route("/reviews/<review_id>/delete", methods=["POST"])
@admin_required
def admin_delete_review(review_id):
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("public.reviews"))

    try:
        client.table("reviews").delete().eq("id", review_id).execute()
        flash("Review deleted.", "success")
    except Exception as exc:
        flash(f"Could not delete review: {exc}", "error")

    return redirect(url_for("public.reviews"))


@bp.route("/dashboard/admin/assignments")
@admin_required
def admin_assignments():
    client = supabase_admin or supabase
    submissions = []

    if not client:
        flash("Supabase client not available.", "error")
        return render_template("admin/admin_assignments.html", submissions=[], email=session.get("user_email"))

    try:
        res = client.table("assignment_submissions").select("*").order("submitted_at", desc=True).execute()
        submissions = res.data or []
        print(f"[ADMIN ASSIGNMENTS] Raw count from DB: {len(submissions)}")

        if submissions:
            student_ids = list({s["student_id"] for s in submissions if s.get("student_id")})
            assignment_ids = list({s["assignment_id"] for s in submissions if s.get("assignment_id")})
            course_ids = list({s["course_id"] for s in submissions if s.get("course_id")})

            names = {}
            if student_ids:
                r = client.table("profiles").select("id, full_name, email, username").in_("id", student_ids).execute()
                for p in (r.data or []):
                    names[p["id"]] = p.get("full_name") or p.get("username") or p.get("email") or "Unknown"

            assignments = {}
            if assignment_ids:
                r = client.table("course_contents").select("id, title").in_("id", assignment_ids).execute()
                for a in (r.data or []):
                    assignments[a["id"]] = a.get("title", "Untitled")

            courses = {}
            if course_ids:
                r = client.table("courses").select("id, title").in_("id", course_ids).execute()
                for c in (r.data or []):
                    courses[c["id"]] = c.get("title", "Untitled")

            for s in submissions:
                s["student_name"] = names.get(s.get("student_id"), "Unknown")
                s["student_email"] = names.get(s.get("student_id"), "") or ""
                s["assignment_title"] = assignments.get(s.get("assignment_id"), "Unknown")
                s["course_title"] = courses.get(s.get("course_id"), "Unknown")

    except Exception as exc:
        print(f"[ADMIN ASSIGNMENTS ERROR] {exc}")
        flash(f"Could not load assignments: {exc}", "error")

    return render_template(
        "admin/admin_assignments.html",
        email=session.get("user_email"),
        submissions=submissions,
    )


#game rout

@bp.route("/admin/daily-challenge", methods=["GET", "POST"])
@admin_required
def admin_daily_challenge():
    client = supabase_admin or supabase

    if request.method == "POST":
        question = request.form.get("question", "").strip()
        correct = request.form.get("correct_answer", "").strip().lower()
        if not question or not correct:
            flash("Question and answer are required.", "error")
            return redirect(url_for("admin.admin_daily_challenge"))

        try:
            from datetime import date
            today = date.today().isoformat()
            client.table("daily_challenges").upsert({
                "challenge_date": today,
                "question": question,
                "correct_answer": correct,
            }, on_conflict="challenge_date").execute()
            flash("Daily challenge set.", "success")
        except Exception as exc:
            flash(f"Error: {exc}", "error")
        return redirect(url_for("admin.admin_daily_challenge"))

    return render_template("admin/admin_daily_challenge.html")

@bp.route("/dashboard/admin/assignments/<submission_id>/review", methods=["POST"])
@admin_required
def admin_review_assignment(submission_id):
    status = request.form.get("status", "").strip()
    admin_note = request.form.get("admin_note", "").strip()

    if status not in ("pending", "approved", "rejected"):
        flash("Invalid status.", "error")
        return redirect(url_for("admin.admin_assignments"))

    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin.admin_assignments"))

    try:
        update_data = {
            "status": status,
            "admin_note": admin_note or None,
        }
        if status in ("approved", "rejected"):
            update_data["reviewed_at"] = datetime.now(timezone.utc).isoformat()

        client.table("assignment_submissions").update(update_data).eq("id", submission_id).execute()
        flash(f"Assignment marked as {status}.", "success")
    except Exception as exc:
        flash(f"Could not update submission: {exc}", "error")

    return redirect(url_for("admin.admin_assignments"))

@bp.route("/admin/assignments/create", methods=["GET", "POST"])
@admin_required
def admin_create_assignment():
    client = supabase_admin or supabase
    courses = []

    if client:
        try:
            res = client.table("courses").select("id, title").eq("is_active", True).order("title").execute()
            courses = res.data or []
        except Exception:
            pass

    if request.method == "POST":
        course_id = request.form.get("course_id", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        sort_order = request.form.get("sort_order", "0").strip()

        if not course_id or not title:
            flash("Course and title are required.", "error")
            return redirect(url_for("admin.admin_create_assignment"))

        try:
            client.table("course_contents").insert({
                "course_id": course_id,
                "title": title,
                "type": "assignment",
                "description": description or None,
                "sort_order": int(sort_order) if sort_order else 0,
            }).execute()
            flash("Assignment created successfully.", "success")
            return redirect(url_for("admin.admin_create_assignment"))
        except Exception as exc:
            flash(f"Failed to create assignment: {exc}", "error")

    return render_template("admin/admin_create_assignment.html", courses=courses)


@bp.route("/admin/assignments")
@admin_required
def admin_assignment_list():
    """Quick redirect to the review page"""
    return redirect(url_for("admin.admin_assignments"))