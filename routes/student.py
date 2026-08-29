import uuid
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, abort
)
from flask import send_file
from io import BytesIO
from werkzeug.utils import secure_filename
from extensions import supabase, supabase_admin
from config import AVATARS_BUCKET, ASSIGNMENTS_BUCKET
from utils import login_required, _get_current_role, _profile_complete, _allowed_image, _allowed_assignment
from cert_utils import is_certificate_eligible, generate_certificate_pdf, generate_verification_code
from config import CERTIFICATES_BUCKET
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
    badges = []
    streak = 0
    points = 0

    if client:
# Profile + streak
        try:
            res = client.table("profiles").select("*").eq("id", user_id).execute()
            if res.data:
                profile = res.data[0]
                streak = profile.get("login_streak") or 0
                points = profile.get("points") or 0

                from datetime import date, timedelta
                today = date.today()
                last = profile.get("last_login_date")

                if last:
                    if isinstance(last, str):
                        last = date.fromisoformat(last[:10])
                    elif hasattr(last, 'date'):
                        last = last.date()

                    if last == today - timedelta(days=1):
                        streak += 1
                    elif last < today - timedelta(days=1):
                        streak = 1
                    # else last == today, don't change
                else:
                    streak = 1

                if last != today:
                    client.table("profiles").update({
                        "login_streak": streak,
                        "last_login_date": today.isoformat()
                    }).eq("id", user_id).execute()
        except Exception as exc:
            print(f"[STREAK ERROR] {exc}")
            streak = 0



        # Courses & enrollments
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

            try:
                a_ids = []
                for cid, items in course_contents.items():
                    for item in items:
                        if item.get("type") == "assignment":
                            a_ids.append(item["id"])
                if a_ids:
                    res = client.table("assignment_submissions").select("*").eq("student_id", user_id).in_("assignment_id", a_ids).execute()
                    for sub in (res.data or []):
                        assignment_submissions[sub["assignment_id"]] = sub
            except Exception:
                pass

    # Calculate badges
    if profile.get("username") and profile.get("phone") and profile.get("college"):
        badges.append({"icon": "🎓", "name": "Profile Pro", "desc": "Completed your profile"})
    if any(e.get("status") == "approved" for e in enrollments):
        badges.append({"icon": "📚", "name": "Course Starter", "desc": "Enrolled in first course"})
    subs = list(assignment_submissions.values())
    if any(s.get("status") == "pending" for s in subs):
        badges.append({"icon": "📝", "name": "Active Learner", "desc": "Submitted an assignment"})
    if any(s.get("status") == "approved" for s in subs):
        badges.append({"icon": "✅", "name": "Approved", "desc": "Assignment approved by admin"})
    if streak >= 3:
        badges.append({"icon": "🔥", "name": "Streak Master", "desc": f"{streak} day login streak"})
    if profile.get("typing_high_score", 0) > 40:
        badges.append({"icon": "⌨️", "name": "Speed Demon", "desc": "Typing score over 40 WPM"})

    enrolled_ids = {e["course_id"] for e in enrollments}
    available_courses = [c for c in all_courses if c["id"] not in enrolled_ids]
    approved_enrollments = [e for e in enrollments if e.get("status") == "approved"]
    pending_enrollments = [e for e in enrollments if e.get("status") == "pending"]

    course_by_id = {c["id"]: c for c in all_courses}

    course_by_id = {c["id"]: c for c in all_courses}

    # Fetch all certificates for this user
    user_certificates = {}
    try:
        res = client.table("certificates").select("*").eq("student_id", user_id).execute()
        for cert in (res.data or []):
            user_certificates[cert["course_id"]] = cert
    except Exception:
        pass

    for e in approved_enrollments:
        e["course"] = course_by_id.get(e["course_id"])
        e["certificate"] = user_certificates.get(e["course_id"])
        if not e["certificate"]:
            e["certificate_eligible"] = is_certificate_eligible(user_id, e["course_id"], client)
        else:
            e["certificate_eligible"] = False

    for e in pending_enrollments:
        e["course"] = course_by_id.get(e["course_id"])

    pending_assignment_count = 0
    for cid, items in course_contents.items():
        for item in items:
            if item.get("type") == "assignment":
                sub = assignment_submissions.get(item["id"])
                if not sub or sub.get("status") == "rejected":
                    pending_assignment_count += 1

    # Daily challenge check
    daily_challenge = None
    daily_answered = False
    try:
        from datetime import date
        today_str = date.today().isoformat()
        res = client.table("daily_challenges").select("*").eq("challenge_date", today_str).execute()
        if res.data:
            daily_challenge = res.data[0]
            # Check if already answered
            ans = client.table("challenge_answers").select("*").eq("student_id", user_id).eq("challenge_id", daily_challenge["id"]).execute()
            daily_answered = bool(ans.data)
    except Exception:
        pass

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
        badges=badges,
        streak=streak,
        points=points,
        typing_high_score=profile.get("typing_high_score", 0),
        daily_challenge=daily_challenge,
        daily_answered=daily_answered,
    )



#game route
@bp.route("/typing-test")
@login_required
def typing_test():
    return render_template("student/typing_test.html")

@bp.route("/typing-test/save", methods=["POST"])
@login_required
def save_typing_score():
    data = request.get_json(force=True, silent=True) or {}
    score = data.get("wpm", 0)
    user_id = session.get("user_id")
    client = supabase_admin

    if not client:
        return {"success": False, "error": "Admin client missing"}

    try:
        res = client.table("profiles").select("typing_high_score, points").eq("id", user_id).execute()
        if not res.data:
            return {"success": False, "error": "Profile not found"}

        current_high = res.data[0].get("typing_high_score") or 0
        current_points = res.data[0].get("points") or 0
        new_high = max(current_high, score)

        # Award 1 point per WPM over 30, capped at 20 per test
        bonus = min(score, 20)

        client.table("profiles").update({
            "typing_high_score": new_high,
            "points": current_points + bonus
        }).eq("id", user_id).execute()

        return {"success": True, "high_score": new_high, "points_earned": bonus}
    except Exception as exc:
        print(f"[TYPING SAVE ERROR] {exc}")
        return {"success": False, "error": str(exc)}



@bp.route("/leaderboard")
@login_required
def leaderboard():
    client = supabase_admin or supabase
    top_students = []
    my_rank = None

    if client:
        try:
            res = client.table("profiles") \
    .select("*") \
    .order("points", desc=True) \
    .order("login_streak", desc=True) \
    .order("typing_high_score", desc=True) \
    .limit(20) \
    .execute()
            all_students = res.data or []
            for i, s in enumerate(all_students, 1):
                s["rank"] = i
                if s["id"] == session.get("user_id"):
                    my_rank = i
            top_students = all_students[:10]
        except Exception as exc:
            print(f"[LEADERBOARD] {exc}")

    return render_template("student/leaderboard.html",
                           students=top_students,
                           my_rank=my_rank)

@bp.route("/daily-challenge/answer", methods=["POST"])
@login_required
def answer_daily_challenge():
    user_id = session.get("user_id")
    challenge_id = request.form.get("challenge_id")
    answer = request.form.get("answer", "").strip().lower()
    client = supabase_admin

    if not client or not challenge_id:
        flash("Server error.", "error")
        return redirect(url_for("student.student_dashboard"))

    try:
        # Check if already answered
        existing = client.table("challenge_answers").select("*") \
            .eq("student_id", user_id).eq("challenge_id", challenge_id).execute()
        if existing.data:
            flash("You already answered today's challenge.", "info")
            return redirect(url_for("student.student_dashboard"))

        # Get correct answer
        ch = client.table("daily_challenges").select("*").eq("id", challenge_id).execute()
        if not ch.data:
            flash("Challenge not found.", "error")
            return redirect(url_for("student.student_dashboard"))

        correct = ch.data[0].get("correct_answer", "").strip().lower()
        is_correct = answer == correct

        # Save answer
        client.table("challenge_answers").insert({
            "challenge_id": challenge_id,
            "student_id": user_id,
            "answer": answer,
            "is_correct": is_correct,
        }).execute()

        if is_correct:
            # Award points
            prof = client.table("profiles").select("points").eq("id", user_id).execute()
            if prof.data:
                new_points = (prof.data[0].get("points", 0) or 0) + 10
                client.table("profiles").update({"points": new_points}).eq("id", user_id).execute()
            flash("🎉 Correct! You earned 10 points.", "success")
        else:
            flash("❌ Wrong answer. Try again tomorrow!", "error")

    except Exception as exc:
        flash(f"Error: {exc}", "error")

    return redirect(url_for("student.student_dashboard"))


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
#CERTIFICATION ROUTE
@bp.route("/certificate/customize/<course_id>")
@login_required
def customize_certificate(course_id):
    user_id = session.get("user_id")
    client = supabase_admin or supabase

    # If already generated, go straight to success
    try:
        existing = client.table("certificates").select("*") \
            .eq("student_id", user_id).eq("course_id", course_id).execute()
        if existing.data:
            return redirect(url_for("student.certificate_success", cert_id=existing.data[0]["id"]))
    except Exception:
        pass

    if not is_certificate_eligible(user_id, course_id, client):
        flash("You are not eligible for a certificate yet. Complete all assignments first.", "error")
        return redirect(url_for("student.student_dashboard"))

    course = None
    if client:
        try:
            res = client.table("courses").select("title").eq("id", course_id).single().execute()
            course = res.data
        except Exception:
            pass

    return render_template("student/customize_certificate.html", course=course, course_id=course_id)

@bp.route("/certificate/generate/<course_id>", methods=["POST"])
@login_required
def generate_certificate(course_id):
    user_id = session.get("user_id")
    client = supabase_admin

    custom_name = request.form.get("custom_name", "").strip()
    print(f"[CERT GEN] Starting for user={user_id}, course={course_id}, name='{custom_name}'")

    if not custom_name or len(custom_name) < 2:
        flash("Please enter a valid name (at least 2 characters).", "error")
        return redirect(url_for("student.customize_certificate", course_id=course_id))

    if not client:
        flash("Server error: admin client not available.", "error")
        return redirect(url_for("student.student_dashboard"))

    # Check if already generated (prevents double-submit)
    try:
        existing = client.table("certificates").select("*") \
            .eq("student_id", user_id).eq("course_id", course_id).execute()
        if existing.data:
            print(f"[CERT GEN] Already exists: {existing.data[0]['id']}")
            flash("Certificate already generated.", "info")
            return redirect(url_for("student.certificate_success", cert_id=existing.data[0]["id"]))
    except Exception as exc:
        print(f"[CERT GEN] Existing check error: {exc}")

    # Check eligibility
    if not is_certificate_eligible(user_id, course_id, client):
        print(f"[CERT GEN] NOT ELIGIBLE")
        flash("You are not eligible for a certificate yet. Complete all assignments first.", "error")
        return redirect(url_for("student.student_dashboard"))

    try:
        course = client.table("courses").select("title").eq("id", course_id).single().execute()
        course_name = course.data.get("title", "Course")
        print(f"[CERT GEN] Course: {course_name}")

        verification_code = generate_verification_code()
        print(f"[CERT GEN] Code: {verification_code}")

        pdf_buffer = generate_certificate_pdf(custom_name, course_name, verification_code)
        pdf_bytes = pdf_buffer.getvalue()
        print(f"[CERT GEN] PDF size: {len(pdf_bytes)} bytes")

        storage_path = f"{user_id}_{course_id}_{uuid.uuid4().hex}.pdf"
        print(f"[CERT GEN] Uploading to: {storage_path}")

        client.storage.from_(CERTIFICATES_BUCKET).upload(
            storage_path,
            pdf_bytes,
            {"content-type": "application/pdf"}
        )
        print(f"[CERT GEN] Upload OK")

        public_url = client.storage.from_(CERTIFICATES_BUCKET).get_public_url(storage_path)
        print(f"[CERT GEN] Public URL: {public_url}")

        insert_data = {
            "student_id": user_id,
            "course_id": course_id,
            "verification_code": verification_code,
            "file_url": public_url,
            "storage_path": storage_path,
        }
        print(f"[CERT GEN] Inserting: {insert_data}")

        result = client.table("certificates").insert(insert_data).execute()
        print(f"[CERT GEN] Insert result: {result}")

        if not result.data:
            print(f"[CERT GEN] ERROR: insert returned no data")
            flash("Certificate saved to storage but database insert failed.", "error")
            return redirect(url_for("student.student_dashboard"))

        cert_id = result.data[0]["id"]
        print(f"[CERT GEN] Cert ID: {cert_id}")

        # Update enrollment
        client.table("enrollments").update({
            "certificate_generated": True
        }).eq("student_id", user_id).eq("course_id", course_id).execute()

        flash(f"Certificate generated! Code: {verification_code}", "success")
        print(f"[CERT GEN] Redirecting to success page: {cert_id}")
        return redirect(url_for("student.certificate_success", cert_id=cert_id))

    except Exception as exc:
        import traceback
        print(f"[CERT GEN] CRASH: {exc}")
        traceback.print_exc()
        flash(f"Could not generate certificate: {exc}", "error")
        return redirect(url_for("student.student_dashboard"))


@bp.route("/certificate/success/<cert_id>")
@login_required
def certificate_success(cert_id):
    """Shows the verification code and a download button."""
    user_id = session.get("user_id")
    client = supabase_admin

    cert = None
    if client:
        try:
            res = client.table("certificates") \
                .select("*, courses(title)").eq("id", cert_id).single().execute()
            if res.data and res.data["student_id"] == user_id:
                cert = res.data
        except Exception:
            pass

    if not cert:
        flash("Certificate not found.", "error")
        return redirect(url_for("student.student_dashboard"))

    return render_template("student/certificate_success.html", cert=cert)



@bp.route("/certificate/test-download")
@login_required
def test_download():
    """Creates a dummy PDF on-the-fly and forces download."""
    from io import BytesIO
    from flask import make_response
    
    # Create a minimal valid PDF (header only, enough to trigger download)
    dummy_pdf = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n196\n%%EOF"
    
    response = make_response(dummy_pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = 'attachment; filename="test.pdf"'
    return response
@bp.route("/certificate/download/<cert_id>")
@login_required
def download_certificate(cert_id):
    user_id = session.get("user_id")
    client = supabase_admin

    if not client:
        flash("Server error.", "error")
        return redirect(url_for("student.student_dashboard"))

    try:
        # 1. Get cert record
        cert_res = client.table("certificates").select("*").eq("id", cert_id).single().execute()
        if not cert_res.data or cert_res.data["student_id"] != user_id:
            flash("Certificate not found.", "error")
            return redirect(url_for("student.student_dashboard"))

        cert = cert_res.data
        storage_path = cert["storage_path"]
        filename = f"GrowthSteps_Certificate_{cert['verification_code']}.pdf"

        print(f"[DOWNLOAD] Fetching: bucket={CERTIFICATES_BUCKET}, path={storage_path}")

        # 2. Get bytes from Supabase
        file_bytes = client.storage.from_(CERTIFICATES_BUCKET).download(storage_path)
        print(f"[DOWNLOAD] Fetched {len(file_bytes)} bytes")

        if not file_bytes or len(file_bytes) < 100:
            flash("File appears empty.", "error")
            return redirect(url_for("student.student_dashboard"))

        # 3. Build response manually (100% reliable)
        response = make_response(file_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"attachment; filename=\"{filename}\""
        response.headers["Content-Length"] = str(len(file_bytes))

        print(f"[DOWNLOAD] Sending response with attachment header")
        return response

    except Exception as exc:
        print(f"[DOWNLOAD ERROR] {exc}")
        # Ultimate fallback: redirect to public URL
        try:
            if cert and cert.get("file_url"):
                flash("Opening certificate...", "info")
                return redirect(cert["file_url"])
        except:
            pass
        flash(f"Download failed: {exc}", "error")
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
