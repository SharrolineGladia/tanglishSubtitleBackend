from flask import Flask
from api.routes import api_bp
import os
from config import Config
import whisper_loader

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    whisper_loader.initialize_models()  # Preload faster-whisper

    app.register_blueprint(api_bp, url_prefix='/api')

    @app.route('/')
    def index():
        return {
            'status': 'online',
            'message': 'Tanglish Subtitle Generation API is running'
        }

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=app.config['DEBUG'], host=app.config['HOST'], port=app.config['PORT'])
