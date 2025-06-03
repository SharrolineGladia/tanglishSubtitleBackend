import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    DEBUG = os.environ.get('DEBUG') or False
    HOST = os.environ.get('HOST') or '0.0.0.0'
    PORT = int(7860)
    
    # File upload settings
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static/temp')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload size
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'mkv'}