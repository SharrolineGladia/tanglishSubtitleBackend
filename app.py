from flask import Flask
from api.routes import api_bp
import os
import time
import shutil
from datetime import datetime
from config import Config
from api.services.whisper_functions import get_whisper_model, cleanup_models
import threading
import atexit

class CleanupService:
    """Automatic cleanup service for temporary files"""
    
    def __init__(self, temp_dir, results_cleanup_minutes=10, folder_cleanup_hours=2):
        self.temp_dir = temp_dir
        self.results_cleanup_time = results_cleanup_minutes * 60  # Convert to seconds
        self.folder_cleanup_time = folder_cleanup_hours * 60 * 60  # Convert to seconds
        self.running = False
        self.cleanup_thread = None
        
    def start(self):
        """Start the cleanup service"""
        if self.running:
            return
            
        self.running = True
        print(f"🧹 Starting cleanup service for {self.temp_dir}")
        print(f"   - Results cleanup: {self.results_cleanup_time/60} minutes")
        print(f"   - Folder cleanup: {self.folder_cleanup_time/3600} hours")
        
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
        
    def stop(self):
        """Stop the cleanup service"""
        self.running = False
        
    def _cleanup_loop(self):
        """Main cleanup loop that runs every 5 minutes"""
        while self.running:
            try:
                self._perform_cleanup()
            except Exception as e:
                print(f"❌ Cleanup error: {e}")
            
            # Wait 5 minutes before next cleanup
            time.sleep(5 * 60)
            
    def _perform_cleanup(self):
        """Perform the actual cleanup of temp files"""
        if not os.path.exists(self.temp_dir):
            return
            
        current_time = time.time()
        folders_cleaned = 0
        
        try:
            folders = os.listdir(self.temp_dir)
            
            for folder_name in folders:
                folder_path = os.path.join(self.temp_dir, folder_name)
                
                if not os.path.isdir(folder_path):
                    continue
                    
                try:
                    # Check if folder is being actively processed
                    lock_file = os.path.join(folder_path, '.processing')
                    if os.path.exists(lock_file):
                        continue
                    
                    should_delete = False
                    reason = ""
                    
                    # Check folder age (2 hours)
                    folder_creation_time = os.path.getctime(folder_path)
                    folder_age = current_time - folder_creation_time
                    
                    if folder_age > self.folder_cleanup_time:
                        should_delete = True
                        reason = f"folder age ({folder_age/3600:.1f}h)"
                    else:
                        # Check results.txt age (10 minutes)
                        results_file = os.path.join(folder_path, 'results.txt')
                        if os.path.exists(results_file):
                            results_creation_time = os.path.getctime(results_file)
                            results_age = current_time - results_creation_time
                            
                            if results_age > self.results_cleanup_time:
                                should_delete = True
                                reason = f"results.txt age ({results_age/60:.1f}min)"
                    
                    if should_delete:
                        shutil.rmtree(folder_path)
                        folders_cleaned += 1
                        print(f"🗑️  Cleaned: {folder_name} ({reason})")
                        
                except Exception as e:
                    print(f"⚠️  Couldn't process folder {folder_name}: {e}")
                    
        except Exception as e:
            print(f"❌ Error listing temp directory: {e}")
            
    def _force_cleanup(self):
        """Force cleanup all folders regardless of age (respects .processing locks)"""
        if not os.path.exists(self.temp_dir):
            return 0
            
        folders_cleaned = 0
        
        try:
            folders = os.listdir(self.temp_dir)
            
            for folder_name in folders:
                folder_path = os.path.join(self.temp_dir, folder_name)
                
                if not os.path.isdir(folder_path):
                    continue
                    
                try:
                    # Still respect processing locks
                    lock_file = os.path.join(folder_path, '.processing')
                    if os.path.exists(lock_file):
                        print(f"⏳ Skipping {folder_name} (currently processing)")
                        continue
                    
                    shutil.rmtree(folder_path)
                    folders_cleaned += 1
                    print(f"🗑️  Force cleaned: {folder_name}")
                        
                except Exception as e:
                    print(f"⚠️  Couldn't force clean folder {folder_name}: {e}")
                    
        except Exception as e:
            print(f"❌ Error in force cleanup: {e}")
            
        print(f"✅ Force cleanup completed: {folders_cleaned} folders removed")
        return folders_cleaned

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Create upload directory
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize cleanup service
    # Assuming your UPLOAD_FOLDER is the static directory
    temp_dir = os.path.join('static', 'temp')  # Direct path to static/temp
    
    # Create temp directory if it doesn't exist
    os.makedirs(temp_dir, exist_ok=True)
    
    cleanup_service = CleanupService(
        temp_dir=temp_dir,
        results_cleanup_minutes=10,  # Clean after 10 minutes if results.txt exists
        folder_cleanup_hours=2       # Clean after 2 hours regardless
    )
    
    # Store cleanup service in app context for access in routes if needed
    app.cleanup_service = cleanup_service
    
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
    
    # Start cleanup service
    cleanup_service.start()
    
    # Register cleanup functions
    def cleanup_on_exit():
        cleanup_service.stop()
        cleanup_models()
    
    atexit.register(cleanup_on_exit)
    
    # Register blueprints
    app.register_blueprint(api_bp, url_prefix='/api')
    
    @app.route('/')
    def index():
        return {
            'status': 'online',
            'message': 'Tanglish Subtitle Generation API is running',
            'using': 'whisper_functions.py model management',
            'cleanup_service': 'active'
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
            'loaded_models': list(_whisper_models.keys()),
            'cleanup_service': 'running' if cleanup_service.running else 'stopped'
        }
    
    @app.route('/api/cleanup/status')
    def cleanup_status():
        """Check cleanup service status"""
        return {
            'status': 'success',
            'cleanup_service': {
                'running': cleanup_service.running,
                'temp_dir': cleanup_service.temp_dir,
                'results_cleanup_minutes': cleanup_service.results_cleanup_time / 60,
                'folder_cleanup_hours': cleanup_service.folder_cleanup_time / 3600
            }
        }
    
    @app.route('/api/cleanup/manual', methods=['POST'])
    def manual_cleanup():
        """Manually trigger cleanup with optional force parameter"""
        from flask import request
        
        try:
            force = request.json.get('force', False) if request.is_json else False
            
            if force:
                # Force cleanup - delete all folders regardless of age
                folders_cleaned = cleanup_service._force_cleanup()
                return {
                    'status': 'success',
                    'message': f'Force cleanup completed - {folders_cleaned} folders removed',
                    'type': 'force'
                }
            else:
                # Normal cleanup with conditions
                cleanup_service._perform_cleanup()
                return {
                    'status': 'success',
                    'message': 'Manual cleanup completed (conditions applied)',
                    'type': 'conditional'
                }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Cleanup failed: {str(e)}'
            }, 500
    
    return app

def run_app():
    """Run the app with whisper_functions.py model management"""
    app = create_app()
    
    print("Starting Flask server with whisper_functions.py...")
    print("Models are loading in the background. Check /api/models for status.")
    print("🧹 Cleanup service is active and will run every 5 minutes.")
    
    app.run(
        debug=app.config['DEBUG'],
        host=app.config['HOST'],
        port=app.config['PORT']
    )

if __name__ == '__main__':
    run_app()