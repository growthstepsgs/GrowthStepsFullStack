from .public import bp as public_bp
from .auth import bp as auth_bp
from .admin import bp as admin_bp
from .employee import bp as employee_bp
from .student import bp as student_bp

__all__ = ["public_bp", "auth_bp", "admin_bp", "employee_bp", "student_bp"]