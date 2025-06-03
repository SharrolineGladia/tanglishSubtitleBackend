from flask import Flask
from api.routes import api_bp
import os
from config import Config
from api.services.whisper_functions import get_whisper_model, cleanup_models
import threading
import atexit

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Create upload directory
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize Whisper models from whisper_functions.py
    print("Initializing Whisper models from whisper_functions.py...")
    
    # Pre-load models in background
    def preload_models():
        try:
            # Get model sizes from config or use defaults
            model_sizes = getattr(app.config, 'WHISPER_MODEL_SIZES', ["base"])
            
            for model_size in model_sizes:
                print(f"Pre-loading {model_size} model...")
                get_whisper_model(model_size)
                print(f"✓ {model_size} model loaded successfully")
                
        except Exception as e:
            print(f"Error pre-loading models: {e}")
    
    # Start background model loading
    preload_thread = threading.Thread(target=preload_models)
    preload_thread.daemon = True
    preload_thread.start()
    
    # Register cleanup function
    atexit.register(cleanup_models)
    
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
        # Since whisper_functions.py uses a global _whisper_models dict
        from whisper_functions import _whisper_models
        
        return {
            'status': 'success',
            'loaded_models': list(_whisper_models.keys()),
            'model_count': len(_whisper_models)
        }
    
    @app.route('/api/health')
    def health_check():
        """Health check endpoint"""
        from whisper_functions import _whisper_models
        
        return {
            'status': 'healthy',
            'models_loaded': len(_whisper_models),
            'loaded_models': list(_whisper_models.keys())
        }
    
    return app

def run_app():
    """Run the app with whisper_functions.py model management"""
    app = create_app()
    
    print("Starting Flask server with whisper_functions.py...")
    print("Models are loading in the background. Check /api/models for status.")
    
    app.run(
        debug=app.config['DEBUG'],
        host=app.config['HOST'],
        port=app.config['PORT']
    )

if __name__ == '__main__':
    run_app()