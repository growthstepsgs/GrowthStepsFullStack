from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
import config
from routes.public import bp as public_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=3600,
    )

    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        print("\n⚠️  SUPABASE NOT CONFIGURED — check your .env file.")
    if config.SUPABASE_URL and config.SUPABASE_KEY and not config.SUPABASE_SERVICE_KEY:
        print("i  No SUPABASE_SERVICE_KEY — admin features may be limited.")

    from routes import public_bp, auth_bp, admin_bp, employee_bp, student_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(student_bp)
    

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)