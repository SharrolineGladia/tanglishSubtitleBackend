# api/routes.py - Fixed version with proper application context handling

from flask import Blueprint, request, jsonify, current_app, send_file
import os
import uuid
import time
import zipfile
import threading
from werkzeug.utils import secure_filename

from api.services.audio_service import extract_audio_from_video, convert_audio_format, split_audio
from api.services.transcription_service import process_pure_tamil_from_audio, transcribe_with_whisper
from api.services.translation_service import translate_text
from api.services.tanglish_service import tamil_to_tanglish, contains_tamil_script
from api.services.srt_service import generate_all_srt_files_improved  # Updated import
from utils.file_utils import allowed_file, cleanup_temp_files

api_bp = Blueprint('api', __name__)

# Store processing status
processing_status = {}

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

def process_video_async(upload_id, app):
    """
    Async function to process video in background with proper app context
    """
    with app.app_context():  # Create application context for the background thread
        try:
            processing_status[upload_id] = {'status': 'processing', 'progress': 0, 'message': 'Starting processing...'}
            
            # Get the upload directory
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
            
            # Get the video file
            files = os.listdir(upload_dir)
            video_files = [f for f in files if allowed_file(f, current_app.config['ALLOWED_EXTENSIONS'])]
            if not video_files:
                raise Exception("No valid video file found")
            
            video_path = os.path.join(upload_dir, video_files[0])
            
            # Step 1: Extract and prepare audio (20% progress)
            processing_status[upload_id]['message'] = 'Extracting audio from video...'
            audio_path = os.path.join(upload_dir, "extracted_audio.mp3")
            wav_audio_path = os.path.join(upload_dir, "audio_for_speech.wav")
            
            extract_audio_from_video(video_path, audio_path)
            convert_audio_format(audio_path, wav_audio_path)
            processing_status[upload_id]['progress'] = 20
            
            # Step 2: Split audio (30% progress)
            processing_status[upload_id]['message'] = 'Preparing audio chunks...'
            chunks = split_audio(wav_audio_path, chunk_length_ms=15000, output_dir=upload_dir)
            processing_status[upload_id]['progress'] = 30
            
            # Step 3: Process Tamil transcription (50% progress)
            processing_status[upload_id]['message'] = 'Transcribing Tamil audio...'
            pure_tamil_text = process_pure_tamil_from_audio(chunks)
            processing_status[upload_id]['progress'] = 50
            
            # Step 4: Generate Tanglish (60% progress)
            processing_status[upload_id]['message'] = 'Converting to Tanglish...'
            if contains_tamil_script(pure_tamil_text):
                romanized_tanglish = tamil_to_tanglish(pure_tamil_text)
            else:
                romanized_tanglish = "Tamil transcription failed"
            processing_status[upload_id]['progress'] = 60
            
            # Step 5: English transcription (70% progress)
            processing_status[upload_id]['message'] = 'Generating English translation...'
            english_text = transcribe_with_whisper(wav_audio_path, language="en")
            if not english_text and pure_tamil_text:
                english_text = translate_text(pure_tamil_text, "ta", "en")
            processing_status[upload_id]['progress'] = 70
            
            # Step 6: Standard Tamil translation (80% progress)
            processing_status[upload_id]['message'] = 'Generating standard Tamil translation...'
            standard_tamil_text = translate_text(english_text, "en", "ta") if english_text else ""
            processing_status[upload_id]['progress'] = 80
            
            # Step 7: Generate SRT files (90% progress)
            processing_status[upload_id]['message'] = 'Generating synchronized subtitle files...'
            results = {
                'pure_tamil': pure_tamil_text,
                'english': english_text,
                'tanglish': romanized_tanglish,
                'standard_tamil': standard_tamil_text
            }
            
            srt_files = generate_all_srt_files_improved(upload_dir, video_path, wav_audio_path, results)
            processing_status[upload_id]['progress'] = 90
            
            # Step 8: Create results file (100% progress)
            processing_status[upload_id]['message'] = 'Finalizing results...'
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
            
            # Complete
            processing_status[upload_id] = {
                'status': 'completed',
                'progress': 100,
                'message': 'Processing completed successfully',
                'results': results,
                'srt_files': {
                    'tamil': 'tamil_subtitles.srt' if 'tamil' in srt_files else None,
                    'english': 'english_subtitles.srt' if 'english' in srt_files else None,
                    'tanglish': 'tanglish_subtitles.srt' if 'tanglish' in srt_files else None,
                    'standard_tamil': 'standard_tamil_subtitles.srt' if 'standard_tamil' in srt_files else None
                },
                'srt_count': len(srt_files)
            }
            
        except Exception as e:
            processing_status[upload_id] = {
                'status': 'error',
                'progress': 0,
                'message': f'Processing failed: {str(e)}'
            }

@api_bp.route('/process/<upload_id>', methods=['POST'])
def process_video(upload_id):
    """
    Endpoint to start processing an uploaded video
    Returns immediately with processing status
    """
    try:
        # Get the upload directory
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        if not os.path.exists(upload_dir):
            return jsonify({'error': 'Invalid upload ID'}), 404
        
        # Check if already processing
        if upload_id in processing_status and processing_status[upload_id]['status'] == 'processing':
            return jsonify({'message': 'Already processing', 'status': 'processing'}), 200
        
        # Check if already completed
        if upload_id in processing_status and processing_status[upload_id]['status'] == 'completed':
            return jsonify(processing_status[upload_id]), 200
        
        # Start async processing - Pass the app instance to the thread
        thread = threading.Thread(target=process_video_async, args=(upload_id, current_app._get_current_object()))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'processing_started',
            'upload_id': upload_id,
            'message': 'Video processing started. Use /status endpoint to check progress.'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@api_bp.route('/status/<upload_id>', methods=['GET'])
def get_processing_status(upload_id):
    """
    Endpoint to check processing status
    """
    if upload_id not in processing_status:
        return jsonify({'error': 'No processing found for this upload ID'}), 404
    
    return jsonify(processing_status[upload_id])

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

@api_bp.route('/download-srt/<upload_id>/<srt_type>', methods=['GET'])
def download_srt(upload_id, srt_type):
    """
    Endpoint to download individual SRT files
    """
    try:
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        
        srt_filenames = {
            'tamil': 'tamil_subtitles.srt',
            'english': 'english_subtitles.srt',
            'tanglish': 'tanglish_subtitles.srt',
            'standard_tamil': 'standard_tamil_subtitles.srt'
        }
        
        if srt_type not in srt_filenames:
            return jsonify({'error': 'Invalid SRT type'}), 400
        
        srt_file = os.path.join(upload_dir, srt_filenames[srt_type])
        
        if not os.path.exists(srt_file):
            return jsonify({'error': f'{srt_type.title()} SRT file not found'}), 404
        
        return send_file(
            srt_file,
            mimetype='application/x-subrip',
            as_attachment=True,
            download_name=srt_filenames[srt_type]
        )
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@api_bp.route('/download-all-srt/<upload_id>', methods=['GET'])
def download_all_srt(upload_id):
    """
    Endpoint to download all SRT files as a ZIP archive
    """
    try:
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        
        if not os.path.exists(upload_dir):
            return jsonify({'error': 'Invalid upload ID'}), 404
        
        zip_path = os.path.join(upload_dir, "all_subtitles.zip")
        
        srt_files = [
            ('tamil_subtitles.srt', 'Tamil Subtitles'),
            ('english_subtitles.srt', 'English Subtitles'),
            ('tanglish_subtitles.srt', 'Tanglish Subtitles'),
            ('standard_tamil_subtitles.srt', 'Standard Tamil Subtitles')
        ]
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            files_added = 0
            for filename, description in srt_files:
                file_path = os.path.join(upload_dir, filename)
                if os.path.exists(file_path):
                    zipf.write(file_path, filename)
                    files_added += 1
            
            results_file = os.path.join(upload_dir, "results.txt")
            if os.path.exists(results_file):
                zipf.write(results_file, "transcription_results.txt")
                files_added += 1
        
        if files_added == 0:
            return jsonify({'error': 'No subtitle files found'}), 404
        
        return send_file(
            zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'subtitles_{upload_id[:8]}.zip'
        )
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@api_bp.route('/list-files/<upload_id>', methods=['GET'])
def list_files(upload_id):
    """
    Endpoint to list all available files for an upload
    """
    try:
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        
        if not os.path.exists(upload_dir):
            return jsonify({'error': 'Invalid upload ID'}), 404
        
        files = os.listdir(upload_dir)
        
        available_files = {
            'srt_files': [f for f in files if f.endswith('.srt')],
            'text_files': [f for f in files if f.endswith('.txt')],
            'audio_files': [f for f in files if f.endswith(('.mp3', '.wav'))],
            'video_files': [f for f in files if not f.endswith(('.srt', '.txt', '.mp3', '.wav'))],
            'all_files': files
        }
        
        return jsonify({
            'status': 'success',
            'upload_id': upload_id,
            'files': available_files
        })
        
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
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        
        if not os.path.exists(upload_dir):
            return jsonify({'error': 'Invalid upload ID'}), 404
        
        cleanup_temp_files([upload_dir])
        
        # Remove from processing status
        if upload_id in processing_status:
            del processing_status[upload_id]
        
        return jsonify({
            'status': 'success',
            'message': 'Temporary files cleaned up successfully'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500