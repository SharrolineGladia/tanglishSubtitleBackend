from flask import Flask
from api.routes import api_bp
import os
import threading
import atexit
from config import Config
from api.services.whisper_functions import get_whisper_model, cleanup_models
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Create upload directory
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize Whisper models from whisper_functions.py
    logger.info("Initializing Whisper models from whisper_functions.py...")
    
    def preload_models():
        try:
            # Get model sizes from config or use defaults
            # For 1GB RAM on Fly.io, use "small" model for best balance
            model_sizes = getattr(app.config, 'WHISPER_MODEL_SIZES', ["small"])
            
            for model_size in model_sizes:
                logger.info(f"Pre-loading {model_size} model...")
                get_whisper_model(model_size)
                logger.info(f"✓ {model_size} model loaded successfully")
                
        except Exception as e:
            logger.error(f"Error pre-loading models: {e}")
            raise
    
    # Start background model loading
    preload_thread = threading.Thread(target=preload_models)
    preload_thread.daemon = True
    preload_thread.start()
    
    # Register cleanup functions for graceful shutdown
    def cleanup_on_exit():
        cleanup_models()
    
    atexit.register(cleanup_on_exit)
    
    # Register blueprints
    app.register_blueprint(api_bp, url_prefix='/api')
    
    @app.route('/')
    def index():
        return {
            'status': 'online',
            'message': 'Tanglish Subtitle Generation API is running',
            'using': 'whisper_functions.py model management'
        }
    
    @app.route('/api/models')
    def models_status():
        """Endpoint to check model loading status"""
        try:
            from api.services.whisper_functions import _whisper_models
            return {
                'status': 'success',
                'loaded_models': list(_whisper_models.keys()),
                'model_count': len(_whisper_models)
            }
        except ImportError:
            return {
                'status': 'error',
                'message': 'whisper_functions module not found'
            }, 500
    
    @app.route('/api/health')
    def health_check():
        """Health check endpoint for Fly.io"""
        try:
            from api.services.whisper_functions import _whisper_models
            return {
                'status': 'healthy',
                'models_loaded': len(_whisper_models),
                'loaded_models': list(_whisper_models.keys())
            }
        except ImportError:
            return {
                'status': 'unhealthy',
                'message': 'whisper_functions module not available'
            }, 500
    
    @app.route('/api/memory')
    def memory_usage():
        """Check memory usage - useful for monitoring on Fly.io"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return {
                "rss_mb": round(memory_info.rss / 1024 / 1024, 2),  # Physical memory
                "vms_mb": round(memory_info.vms / 1024 / 1024, 2),  # Virtual memory
                "percent": round(process.memory_percent(), 2)
            }
        except ImportError:
            return {
                'status': 'error',
                'message': 'psutil not available'
            }, 500
    
    return app

def run_app():
    """Run the app with whisper_functions.py model management"""
    app = create_app()
    
    logger.info("Starting Flask server with whisper_functions.py...")
    logger.info("Models are loading in the background. Check /api/models for status.")
    
    # For production deployment on Fly.io
    port = int(os.environ.get('PORT', app.config.get('PORT', 7860)))
    host = os.environ.get('HOST', app.config.get('HOST', '0.0.0.0'))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    app.run(
        debug=debug,
        host=host,
        port=port
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)


# For WSGI servers like gunicorn
application = create_app()
app = application