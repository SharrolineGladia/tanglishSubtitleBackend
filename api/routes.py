from flask import Blueprint, request, jsonify, current_app, send_file
import os
import uuid
import time
from werkzeug.utils import secure_filename

from api.services.audio_service import extract_audio_from_video, convert_audio_format, split_audio
from api.services.transcription_service import process_pure_tamil_from_audio, transcribe_with_whisper
from api.services.translation_service import translate_text
from api.services.tanglish_service import tamil_to_tanglish, contains_tamil_script
from utils.file_utils import allowed_file, cleanup_temp_files

api_bp = Blueprint('api', __name__)

@api_bp.route('/upload', methods=['POST'])
def upload_video():
    """
    Endpoint to upload a video file
    Returns a unique ID for the uploaded file
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename, current_app.config['ALLOWED_EXTENSIONS']):
        # Create a unique ID for this upload
        upload_id = str(uuid.uuid4())
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save the uploaded file
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        return jsonify({
            'status': 'success',
            'upload_id': upload_id,
            'filename': filename,
            'message': 'Video uploaded successfully'
        })
    
    return jsonify({'error': 'File type not allowed'}), 400

@api_bp.route('/process/<upload_id>', methods=['POST'])
def process_video(upload_id):
    """
    Endpoint to process an uploaded video and generate subtitles
    """
    try:
        # Get the upload directory
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        if not os.path.exists(upload_dir):
            return jsonify({'error': 'Invalid upload ID'}), 404
        
        # Get the video file
        files = os.listdir(upload_dir)
        video_files = [f for f in files if allowed_file(f, current_app.config['ALLOWED_EXTENSIONS'])]
        
        if not video_files:
            return jsonify({'error': 'No valid video file found'}), 404
        
        video_path = os.path.join(upload_dir, video_files[0])
        
        # Extract and prepare audio
        audio_path = os.path.join(upload_dir, "extracted_audio.mp3")
        wav_audio_path = os.path.join(upload_dir, "audio_for_speech.wav")
        
        extract_audio_from_video(video_path, audio_path)
        convert_audio_format(audio_path, wav_audio_path)
        
        # Split audio into smaller chunks for more reliable processing
        chunks = split_audio(wav_audio_path, chunk_length_ms=15000, output_dir=upload_dir)
        
        # Process pure Tamil text directly from audio
        pure_tamil_text = process_pure_tamil_from_audio(chunks)
        
        # If we have Tamil script, convert to Tanglish for reference
        if contains_tamil_script(pure_tamil_text):
            romanized_tanglish = tamil_to_tanglish(pure_tamil_text)
        else:
            romanized_tanglish = "Tamil transcription failed"
        
        # Use Whisper for English translation
        english_text = transcribe_with_whisper(wav_audio_path, language="en")
        
        # If Whisper English fails, try translating from Tamil
        if not english_text and pure_tamil_text:
            english_text = translate_text(pure_tamil_text, "ta", "en")
        
        # Get standard Tamil translation from English (for comparison)
        standard_tamil_text = translate_text(english_text, "en", "ta") if english_text else ""
        
        # Create a results file
        results_file = os.path.join(upload_dir, "results.txt")
        with open(results_file, "w", encoding="utf-8") as f:
            f.write("===== TAMIL TRANSCRIPTION RESULTS =====\n\n")
            f.write("PURE TAMIL TEXT (DIRECT FROM AUDIO):\n")
            f.write(pure_tamil_text)
            f.write("\n\nENGLISH TRANSLATION:\n")
            f.write(english_text)
            f.write("\n\nTANGLISH ROMANIZATION:\n")
            f.write(romanized_tanglish)
            f.write("\n\nSTANDARD TAMIL TEXT (FROM ENGLISH):\n")
            f.write(standard_tamil_text)
        
        # Return the results
        return jsonify({
            'status': 'success',
            'upload_id': upload_id,
            'results': {
                'pure_tamil': pure_tamil_text,
                'english': english_text,
                'tanglish': romanized_tanglish,
                'standard_tamil': standard_tamil_text
            }
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@api_bp.route('/download/<upload_id>', methods=['GET'])
def download_results(upload_id):
    """
    Endpoint to download the results text file
    """
    try:
        # Get the results file
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        results_file = os.path.join(upload_dir, "results.txt")
        
        if not os.path.exists(results_file):
            return jsonify({'error': 'Results file not found'}), 404
        
        return send_file(
            results_file,
            mimetype='text/plain',
            as_attachment=True,
            download_name='tamil_transcription_results.txt'
        )
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@api_bp.route('/cleanup/<upload_id>', methods=['DELETE'])
def cleanup(upload_id):
    """
    Endpoint to clean up temporary files
    """
    try:
        # Get the upload directory
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        
        if not os.path.exists(upload_dir):
            return jsonify({'error': 'Invalid upload ID'}), 404
        
        # Clean up the directory
        cleanup_temp_files([upload_dir])
        
        return jsonify({
            'status': 'success',
            'message': 'Temporary files cleaned up successfully'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500