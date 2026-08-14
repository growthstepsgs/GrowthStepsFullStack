import uuid
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, abort
)
from werkzeug.utils import secure_filename
from extensions import supabase, supabase_admin
from config import AVATARS_BUCKET, ASSIGNMENTS_BUCKET
from utils import login_required, _get_current_role, _profile_complete, _allowed_image, _allowed_assignment

bp = Blueprint("student", __name__)


@bp.route("/dashboard/student")
@login_required
def student_dashboard():
    user_id = session.get("user_id")
    role = _get_current_role(user_id)
    session["role"] = role

    if role == "admin":
        return redirect(url_for("admin.admin_dashboard"))
    if role == "employee":
        return redirect(url_for("employee.employee_dashboard"))

    if not _profile_complete(user_id):
        flash("Complete your profile to continue.", "info")
        return redirect(url_for("student.student_profile"))

    client = supabase_admin or supabase

    all_courses = []
    enrollments = []
    course_contents = {}
    profile = {}
    assignment_submissions = {}

    if client:
        try:
            res = client.table("courses").select("*").eq("is_active", True).order("created_at", desc=True).execute()
            all_courses = res.data or []
        except Exception:
            pass

        try:
            res = client.table("enrollments").select("*").eq("student_id", user_id).execute()
            enrollments = res.data or []
        except Exception:
            pass

        approved_ids = [e["course_id"] for e in enrollments if e.get("status") == "approved"]
        if approved_ids:
            try:
                res = client.table("course_contents").select("*").in_("course_id", approved_ids).order("sort_order").execute()
                for item in (res.data or []):
                    cid = item["course_id"]
                    if cid not in course_contents:
                        course_contents[cid] = []
                    course_contents[cid].append(item)
            except Exception:
                pass

            # Fetch assignment submissions for approved courses
            try:
                assignment_ids = []
                for cid, items in course_contents.items():
                    for item in items:
                        if item.get("type") == "assignment":
                            assignment_ids.append(item["id"])
                if assignment_ids:
                    res = client.table("assignment_submissions").select("*").eq("student_id", user_id).in_("assignment_id", assignment_ids).execute()
                    for sub in (res.data or []):
                        assignment_submissions[sub["assignment_id"]] = sub
            except Exception:
                pass

        try:
            res = client.table("profiles").select("*").eq("id", user_id).execute()
            if res.data:
                profile = res.data[0]
        except Exception:
            pass

    enrolled_ids = {e["course_id"] for e in enrollments}
    available_courses = [c for c in all_courses if c["id"] not in enrolled_ids]
    approved_enrollments = [e for e in enrollments if e.get("status") == "approved"]
    pending_enrollments = [e for e in enrollments if e.get("status") == "pending"]

    course_by_id = {c["id"]: c for c in all_courses}
    for e in approved_enrollments:
        e["course"] = course_by_id.get(e["course_id"])
    for e in pending_enrollments:
        e["course"] = course_by_id.get(e["course_id"])

    # Assignment stats
    pending_assignment_count = 0
    for cid, items in course_contents.items():
        for item in items:
            if item.get("type") == "assignment":
                sub = assignment_submissions.get(item["id"])
                if not sub:
                    pending_assignment_count += 1

    return render_template(
        "student/student_dashboard.html",
        email=session.get("user_email"),
        profile=profile,
        approved_enrollments=approved_enrollments,
        pending_enrollments=pending_enrollments,
        available_courses=available_courses,
        course_contents=course_contents,
        assignment_submissions=assignment_submissions,
        pending_assignment_count=pending_assignment_count,
    )


@bp.route("/dashboard/student/profile", methods=["GET", "POST"])
@login_required
def student_profile():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    client = supabase_admin
    profile = {}

    if client:
        try:
            res = client.table("profiles").select("*").eq("id", user_id).execute()
            if res.data:
                profile = res.data[0]
        except Exception:
            pass

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()
        college = request.form.get("college", "").strip()
        gender = request.form.get("gender", "").strip()
        bio = request.form.get("bio", "").strip()

        if not username:
            flash("Username is required.", "error")
            return render_template("student/student_profile.html", profile=profile)

        if not client:
            flash("Server misconfiguration: service key is missing. Contact admin.", "error")
            return render_template("student/student_profile.html", profile=profile)

        update_data = {
            "id": user_id,
            "username": username,
            "phone": phone or None,
            "college": college or None,
            "bio": bio or None,
            "full_name": profile.get("full_name") or "",
            "email": profile.get("email") or session.get("user_email") or "",
        }

        if gender in ("male", "female", "other", "prefer_not_to_say"):
            update_data["gender"] = gender
        else:
            update_data["gender"] = None

        file = request.files.get("avatar")
        if file and file.filename and _allowed_image(file.filename):
            ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
            storage_path = f"{user_id}_{uuid.uuid4().hex}.{ext}"

            try:
                file_bytes = file.read()

                old_path = profile.get("avatar_storage_path")
                if old_path:
                    try:
                        client.storage.from_(AVATARS_BUCKET).remove([old_path])
                    except Exception:
                        pass

                client.storage.from_(AVATARS_BUCKET).upload(
                    storage_path,
                    file_bytes,
                    {"content-type": file.mimetype},
                )
                public_url = client.storage.from_(AVATARS_BUCKET).get_public_url(storage_path)

                update_data["avatar_url"] = public_url
                update_data["avatar_storage_path"] = storage_path
            except Exception as exc:
                flash(f"Avatar upload failed: {exc}", "error")

        try:
            client.table("profiles").upsert(update_data, on_conflict="id").execute()
            session["profile_complete"] = True
            flash("Profile saved successfully.", "success")
            return redirect(url_for("student.student_dashboard"))
        except Exception as exc:
            print(f"[PROFILE SAVE ERROR] {exc}")
            flash(f"Could not save profile: {exc}", "error")
            profile.update(update_data)
            return render_template("student/student_profile.html", profile=profile)

    return render_template("student/student_profile.html", profile=profile)


@bp.route("/enroll/<course_id>", methods=["POST"])
@login_required
def enroll_course(course_id):
    user_id = session.get("user_id")
    role = session.get("role")

    if role != "student":
        flash("Only students can enroll in courses.", "error")
        return redirect(url_for("public.available_courses"))

    client = supabase_admin or supabase
    if not client or not user_id:
        flash("Could not process enrollment.", "error")
        return redirect(url_for("public.available_courses"))

    try:
        existing = client.table("enrollments").select("*").eq("student_id", user_id).eq("course_id", course_id).execute()
        if existing.data:
            flash("You are already enrolled in this course.", "info")
            return redirect(url_for("student.student_dashboard"))

        client.table("enrollments").insert({
            "student_id": user_id,
            "course_id": course_id,
            "status": "pending",
        }).execute()
        flash("Enrollment request submitted! Waiting for admin approval.", "success")
    except Exception as exc:
        flash(f"Enrollment failed: {exc}", "error")

    return redirect(url_for("student.student_dashboard"))


@bp.route("/course/<course_id>/content/<content_id>")
@login_required
def course_content(course_id, content_id):
    user_id = session.get("user_id")
    role = session.get("role")

    if role != "admin":
        client = supabase_admin or supabase
        if client:
            try:
                res = client.table("enrollments").select("*") \
                    .eq("student_id", user_id) \
                    .eq("course_id", course_id) \
                    .eq("status", "approved") \
                    .execute()
                if not res.data:
                    flash("You are not enrolled in this course.", "error")
                    return redirect(url_for("student.student_dashboard"))
            except Exception:
                flash("Could not verify enrollment.", "error")
                return redirect(url_for("student.student_dashboard"))

    client = supabase_admin or supabase
    content = None
    if client:
        try:
            res = client.table("course_contents").select("*") \
                .eq("id", content_id) \
                .eq("course_id", course_id) \
                .execute()
            if res.data:
                content = res.data[0]
        except Exception:
            pass

    if not content:
        abort(404)

    if content.get("url"):
        return redirect(content["url"])

    return render_template("course_content.html", content=content)


@bp.route("/assignment/<content_id>/submit", methods=["GET", "POST"])
@login_required
def submit_assignment(content_id):
    user_id = session.get("user_id")

    # CRITICAL: must use service role for insert to bypass RLS
    client = supabase_admin
    if not client:
        flash("Server error: admin client not available. Check SUPABASE_SERVICE_KEY in .env and restart Flask.", "error")
        return redirect(url_for("student.student_dashboard"))

    # Fetch assignment
    assignment = None
    course_id = None
    try:
        res = client.table("course_contents").select("*").eq("id", content_id).execute()
        if res.data:
            assignment = res.data[0]
            course_id = assignment["course_id"]
    except Exception as exc:
        flash(f"Could not load assignment: {exc}", "error")
        return redirect(url_for("student.student_dashboard"))

    if not assignment or assignment.get("type") != "assignment":
        flash("Assignment not found.", "error")
        return redirect(url_for("student.student_dashboard"))

    # Verify enrollment
    try:
        res = client.table("enrollments").select("*") \
            .eq("student_id", user_id) \
            .eq("course_id", course_id) \
            .eq("status", "approved") \
            .execute()
        if not res.data:
            flash("You are not enrolled in this course.", "error")
            return redirect(url_for("student.student_dashboard"))
    except Exception as exc:
        flash(f"Enrollment check failed: {exc}", "error")
        return redirect(url_for("student.student_dashboard"))

    # Check existing submission
    existing = None
    try:
        res = client.table("assignment_submissions").select("*") \
            .eq("student_id", user_id) \
            .eq("assignment_id", content_id) \
            .execute()
        if res.data:
            existing = res.data[0]
    except Exception as exc:
        print(f"[SUBMIT] Existing check error: {exc}")

    # LOCK: if pending or approved, redirect away immediately
    if existing and existing.get("status") in ("pending", "approved"):
        flash("You have already submitted this assignment. Wait for admin review.", "info")
        return redirect(url_for("student.my_assignments"))

    if request.method == "POST":
        submission_text = request.form.get("submission_text", "").strip()

        if not submission_text and not request.files.get("submission_file"):
            flash("Please provide text or upload a file.", "error")
            return render_template("student/submit_assignment.html",
                                   assignment=assignment, existing=existing)

        insert_data = {
            "assignment_id": content_id,
            "student_id": user_id,
            "course_id": course_id,
            "submission_text": submission_text or None,
            "status": "pending",
        }

        # Handle file upload
        file = request.files.get("submission_file")
        if file and file.filename:
            if not _allowed_assignment(file.filename):
                flash("Unsupported file type. Allowed: pdf, doc, docx, txt, zip, jpg, png, webp", "error")
                return render_template("student/submit_assignment.html",
                                       assignment=assignment, existing=existing)

            ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
            storage_path = f"{user_id}_{content_id}_{uuid.uuid4().hex}.{ext}"

            try:
                file_bytes = file.read()

                if existing and existing.get("file_storage_path"):
                    try:
                        client.storage.from_(ASSIGNMENTS_BUCKET).remove([existing["file_storage_path"]])
                    except Exception:
                        pass

                client.storage.from_(ASSIGNMENTS_BUCKET).upload(
                    storage_path,
                    file_bytes,
                    {"content-type": file.mimetype},
                )
                public_url = client.storage.from_(ASSIGNMENTS_BUCKET).get_public_url(storage_path)
                insert_data["file_url"] = public_url
                insert_data["file_storage_path"] = storage_path
            except Exception as exc:
                flash(f"File upload failed: {exc}", "error")
                return render_template("student/submit_assignment.html",
                                       assignment=assignment, existing=existing)

        # INSERT or UPSERT
        try:
            if existing:
                insert_data["id"] = existing["id"]
                result = client.table("assignment_submissions").upsert(insert_data, on_conflict="id").execute()
            else:
                result = client.table("assignment_submissions").insert(insert_data).execute()

            # VERIFY: read it back immediately
            verify = client.table("assignment_submissions").select("*") \
                .eq("student_id", user_id) \
                .eq("assignment_id", content_id) \
                .execute()

            if not verify.data:
                flash("Submission failed: could not verify save in database.", "error")
                return render_template("student/submit_assignment.html",
                                       assignment=assignment, existing=existing)

            flash("Assignment submitted successfully.", "success")
            return redirect(url_for("student.my_assignments"))

        except Exception as exc:
            flash(f"Could not save submission: {exc}", "error")
            return render_template("student/submit_assignment.html",
                                   assignment=assignment, existing=existing)

    return render_template("student/submit_assignment.html",
                           assignment=assignment, existing=existing)


@bp.route("/my-assignments")
@login_required
def my_assignments():
    user_id = session.get("user_id")
    client = supabase_admin or supabase

    pending_assignments = []
    my_submissions = {}

    if client:
        try:
            res = client.table("enrollments").select("course_id").eq("student_id", user_id).eq("status", "approved").execute()
            course_ids = [e["course_id"] for e in (res.data or [])]

            if course_ids:
                res = client.table("course_contents").select("*, courses(title)").in_("course_id", course_ids).eq("type", "assignment").order("sort_order").execute()
                all_assignments = res.data or []

                if all_assignments:
                    a_ids = [a["id"] for a in all_assignments]
                    res = client.table("assignment_submissions").select("*").eq("student_id", user_id).in_("assignment_id", a_ids).execute()
                    for sub in (res.data or []):
                        my_submissions[sub["assignment_id"]] = sub

                for a in all_assignments:
                    sub = my_submissions.get(a["id"])
                    if not sub or sub.get("status") in ("pending", "rejected"):
                        a["submission"] = sub
                        pending_assignments.append(a)

        except Exception as exc:
            print(f"my_assignments failed: {exc}")

    return render_template("student/my_assignments.html",
                           pending_assignments=pending_assignments)
