from flask import Flask
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    
    # Basic config
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
    
    # Create upload directory
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    @app.route('/')
    def index():
        return {
            'status': 'online',
            'message': 'Tanglish Subtitle Generation API is running',
            'version': '1.0'
        }
    
    @app.route('/api/health')
    def health_check():
        """Health check endpoint for Hugging Face Spaces"""
        return {
            'status': 'healthy',
            'message': 'API is running'
        }
    
    @app.route('/api/memory')
    def memory_usage():
        """Check memory usage"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return {
                "rss_mb": round(memory_info.rss / 1024 / 1024, 2),
                "vms_mb": round(memory_info.vms / 1024 / 1024, 2),
                "percent": round(process.memory_percent(), 2)
            }
        except ImportError:
            return {
                'status': 'error',
                'message': 'psutil not available'
            }, 500
    
    # Try to register your API routes if they exist
    try:
        from api.routes import api_bp
        app.register_blueprint(api_bp, url_prefix='/api')
        logger.info("API routes registered successfully")
    except ImportError as e:
        logger.warning(f"Could not import API routes: {e}")
        
        # Add a simple test route instead
        @app.route('/api/test')
        def test_route():
            return {'message': 'API test route working'}
    
    return app

# Create the application instance
app = create_app()

# For WSGI servers (gunicorn, etc.)
application = app

if __name__ == "__main__":
    # Get port from environment (Hugging Face uses different ports)
    port = int(os.environ.get('PORT', 7860))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(
        debug=False,
        host=host,
        port=port
    )