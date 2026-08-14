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