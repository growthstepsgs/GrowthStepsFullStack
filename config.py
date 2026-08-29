import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

SUPABASE_URL         = os.environ.get("SUPABASE_URL")
SUPABASE_KEY         = os.environ.get("SUPABASE_KEY")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

ADMIN_EMAIL    = "rsvijaysarathi123@gmail.com"
ADMIN_PASSWORD = "v2v24123@v2v24123"

VALID_STATUSES = {"pending", "in_review", "approved", "rejected"}

GALLERY_BUCKET = "Gallery"
AVATARS_BUCKET = "avatars" 
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
ASSIGNMENTS_BUCKET = "assignments"
ALLOWED_ASSIGNMENT_EXTENSIONS = {"pdf", "doc", "docx", "txt", "zip", "jpg", "jpeg", "png", "webp"}

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# ═══════════════════════════════════════════════════════════════════
# CERTIFICATE GENERATION
# ═══════════════════════════════════════════════════════════════════
CERTIFICATE_TEMPLATE_PATH = BASE_DIR / "static" / "assets" / "certificate_template.png"
CERTIFICATES_BUCKET       = "certificates"

# Text positioning — RUN calibrate_certificate.py TO GET EXACT VALUES
CERT_NAME_POS   = (1171.23, 628.04)   # Student name
CERT_COURSE_POS = (1167.33, 768.55)   # Course name
CERT_DATE_POS   = (427.71, 1164.70)   # Issue date
CERT_CODE_POS   = (425.76, 1246.67)   # 10-digit verification code

# Font settings
CERT_FONT_PATH  = BASE_DIR / "static" / "fonts" / "timesbd.ttf"  # or timesbd.ttf
CERT_FONT_SIZE  = 48
CERT_TEXT_COLOR = (0, 0, 0)    # Black