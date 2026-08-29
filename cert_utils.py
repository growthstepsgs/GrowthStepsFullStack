import io
import uuid
import secrets
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

from config import (
    CERTIFICATE_TEMPLATE_PATH,
    CERT_NAME_POS, CERT_COURSE_POS, CERT_DATE_POS, CERT_CODE_POS,
    CERT_FONT_PATH, CERT_FONT_SIZE, CERT_TEXT_COLOR
)


def generate_verification_code():
    """Cryptographically secure 10-digit code."""
    return ''.join(secrets.choice('0123456789') for _ in range(10))


def generate_certificate_pdf(student_name, course_name, verification_code):
    """
    Draws text onto the template image and returns a PDF buffer.
    """
    img = Image.open(CERTIFICATE_TEMPLATE_PATH)

    # Convert to RGB (PDF does not support RGBA well)
    if img.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        if img.mode in ('RGBA', 'LA'):
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert('RGB')

    draw = ImageDraw.Draw(img)

    # Load Times New Roman
    try:
        # Name — largest, the visual focal point (increased)
        font = ImageFont.truetype(str(CERT_FONT_PATH), int(CERT_FONT_SIZE * 1.50))

        # Course — increased, but smaller than the name (separate from date now)
        course_font = ImageFont.truetype(str(CERT_FONT_PATH), int(CERT_FONT_SIZE * 1.00))

        # Date — unchanged, same size as original
        small_font = ImageFont.truetype(str(CERT_FONT_PATH), int(CERT_FONT_SIZE * 0.70))

        # Verification code — unchanged, same size as original
        code_font = ImageFont.truetype(str(CERT_FONT_PATH), int(CERT_FONT_SIZE * 0.65))
    except Exception as e:
        print(f"[CERT FONT ERROR] {e}")
        font = ImageFont.load_default()
        course_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
        code_font = ImageFont.load_default()

    def draw_centered(text, pos, font_obj):
        bbox = draw.textbbox((0, 0), text, font=font_obj)
        text_width = bbox[2] - bbox[0]
        x = pos[0] - (text_width // 2)
        draw.text((x, pos[1]), text, fill=CERT_TEXT_COLOR, font=font_obj)

    today_str = datetime.now().strftime("%B %d, %Y")

    draw_centered(student_name, CERT_NAME_POS, font)
    draw_centered(f"{course_name}", CERT_COURSE_POS, course_font)
    draw_centered(f"Date of Issue: {today_str}", CERT_DATE_POS, small_font)
    draw_centered(f"Verification Code: {verification_code}", CERT_CODE_POS, code_font)

    # Convert drawn image → PDF
    pdf_buffer = io.BytesIO()
    try:
        import img2pdf
        png_buffer = io.BytesIO()
        img.save(png_buffer, format='PNG')
        png_buffer.seek(0)
        pdf_bytes = img2pdf.convert(png_buffer)
        pdf_buffer.write(pdf_bytes)
    except ImportError:
        img.save(pdf_buffer, format="PDF", resolution=100.0)

    pdf_buffer.seek(0)
    return pdf_buffer


def is_certificate_eligible(student_id, course_id, client):
    """
    Returns True ONLY if:
      1. Enrollment is approved
      2. Course has ≥1 assignment
      3. ALL assignments have approved submissions
      4. Certificate has NOT already been generated
    """
    if not client:
        return False

    try:
        # 1. Approved enrollment?
        enroll = client.table("enrollments").select("*") \
            .eq("student_id", student_id) \
            .eq("course_id", course_id) \
            .eq("status", "approved") \
            .execute()
        if not enroll.data:
            return False

        # 2. Any assignments in this course?
        assignments = client.table("course_contents").select("id") \
            .eq("course_id", course_id) \
            .eq("type", "assignment") \
            .execute()
        if not assignments.data:
            return False

        assignment_ids = [a["id"] for a in assignments.data]

        # 3. Already generated?
        existing = client.table("certificates").select("*") \
            .eq("student_id", student_id) \
            .eq("course_id", course_id) \
            .execute()
        if existing.data:
            return False

        # 4. Count approved submissions
        submissions = client.table("assignment_submissions").select("id") \
            .eq("student_id", student_id) \
            .eq("course_id", course_id) \
            .in_("assignment_id", assignment_ids) \
            .eq("status", "approved") \
            .execute()

        return len(submissions.data) == len(assignment_ids)

    except Exception as exc:
        print(f"[CERT ELIGIBILITY ERROR] {exc}")
        return False
