
from flask import Blueprint, request, jsonify, current_app, send_file, Response
import os
import uuid
import time
import zipfile
import threading
import json
from werkzeug.utils import secure_filename
from collections import defaultdict
import queue
from api.services.whisper_functions import (
    process_pure_tamil_from_audio,
    transcribe_with_whisper,
    batch_transcribe_multiple_languages,
    get_whisper_model
)
from api.services.audio_service import extract_audio_from_video, convert_audio_format, split_audio
from api.services.transcription_service import process_pure_tamil_from_audio, transcribe_with_whisper
from api.services.translation_service import translate_text
from api.services.tanglish_service import tamil_to_tanglish, contains_tamil_script
from api.services.srt_service import generate_all_srt_files_improved
from utils.file_utils import allowed_file, cleanup_temp_files

api_bp = Blueprint('api', __name__)

# Store processing status and SSE clients
processing_status = {}
sse_clients = defaultdict(list)  # upload_id -> list of client queues

def broadcast_status_update(upload_id, status_data):
    """Broadcast status update to all SSE clients for this upload_id"""
    processing_status[upload_id] = status_data
    
    # Send to all connected SSE clients for this upload_id
    if upload_id in sse_clients:
        disconnected_clients = []
        for client_queue in sse_clients[upload_id]:
            try:
                client_queue.put(status_data, timeout=1)
            except:
                # Client disconnected, mark for removal
                disconnected_clients.append(client_queue)
        
        # Remove disconnected clients
        for client in disconnected_clients:
            sse_clients[upload_id].remove(client)

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
    Async function to process video in background with real-time status updates
    Enhanced to use unified Whisper functions for better efficiency
    """
    with app.app_context():
        try:
            # Initial status
            broadcast_status_update(upload_id, {
                'status': 'processing', 
                'progress': 0, 
                'message': 'Starting processing...'
            })
            
            # Get the upload directory
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
            
            # Get the video file
            files = os.listdir(upload_dir)
            video_files = [f for f in files if allowed_file(f, current_app.config['ALLOWED_EXTENSIONS'])]
            if not video_files:
                raise Exception("No valid video file found")
            
            video_path = os.path.join(upload_dir, video_files[0])
            
            # Step 1: Extract and prepare audio (20% progress)
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 10,
                'message': 'Extracting audio from video...'
            })
            
            audio_path = os.path.join(upload_dir, "extracted_audio.mp3")
            wav_audio_path = os.path.join(upload_dir, "audio_for_speech.wav")
            
            extract_audio_from_video(video_path, audio_path)
            convert_audio_format(audio_path, wav_audio_path)
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 20,
                'message': 'Audio extraction completed'
            })
            
            # Step 2: Split audio (30% progress)
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 25,
                'message': 'Preparing audio chunks...'
            })
            
            chunks = split_audio(wav_audio_path, chunk_length_ms=15000, output_dir=upload_dir)
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 30,
                'message': 'Audio chunks prepared'
            })
            
            # Step 3: Load Whisper model once for all operations
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 32,
                'message': 'Loading AI models...'
            })
            
            # Pre-load model to avoid repeated loading
            whisper_model = get_whisper_model("base")
            
            # Step 4: Process Tamil transcription (50% progress)
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 35,
                'message': 'Transcribing Tamil audio...'
            })
            
            tanglish_tamil_text = process_pure_tamil_from_audio(chunks, model=whisper_model)
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 50,
                'message': 'Tamil transcription completed'
            })
            
            # Step 5: Generate Tanglish (60% progress)
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 55,
                'message': 'Converting to Tanglish...'
            })
            
            if contains_tamil_script(tanglish_tamil_text):
                tanglish_english_text = tamil_to_tanglish(tanglish_tamil_text)
            else:
                tanglish_english_text = "Tamil transcription failed"
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 60,
                'message': 'Tanglish conversion completed'
            })
            
            # Step 6: English transcription using the same model (70% progress)
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 65,
                'message': 'Generating English translation...'
            })
            
            # FIX: Use the already loaded model directly instead of passing model_size
            try:
                # Method 1: Use the loaded model with transcribe_with_whisper
                english_text = transcribe_with_whisper(
                    wav_audio_path, 
                    language="en"
                    # Removed model_size parameter - let it use default or loaded model
                )
            except Exception as e:
                print(f"transcribe_with_whisper failed: {e}")
                # Method 2: Fallback - use the model directly
                try:
                    segments, _ = whisper_model.transcribe(wav_audio_path, language="en", beam_size=5)
                    english_text = " ".join([seg.text for seg in segments])
                except Exception as e2:
                    print(f"Direct model transcription failed: {e2}")
                    english_text = ""
            
            # Fallback to translation if direct transcription fails
            if not english_text and tanglish_tamil_text:
                english_text = translate_text(tanglish_tamil_text, "ta", "en")
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 70,
                'message': 'English translation completed'
            })
            
            # Step 7: Standard Tamil translation (80% progress)
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 75,
                'message': 'Generating standard Tamil translation...'
            })
            
            tamil_text = translate_text(english_text, "en", "ta") if english_text else ""
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 80,
                'message': 'Standard Tamil translation completed'
            })
            
            # Step 8: Generate SRT files (90% progress)
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 85,
                'message': 'Generating synchronized subtitle files...'
            })
            
            results = {
                'tanglish_tamil': tanglish_tamil_text,
                'english': english_text,
                'tanglish_english': tanglish_english_text,
                'tamil': tamil_text
            }
            
            # The SRT service will use the unified whisper functions internally
            srt_files = generate_all_srt_files_improved(upload_dir, video_path, wav_audio_path, results)
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 90,
                'message': 'Subtitle files generated'
            })
            
            # Step 9: Create results file (100% progress)
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 95,
                'message': 'Finalizing results...'
            })
            
            results_file = os.path.join(upload_dir, "results.txt")
            with open(results_file, "w", encoding="utf-8") as f:
                f.write("===== TRANSCRIPTION RESULTS =====\n\n")
                f.write("TANGLISH IN TAMIL TEXT (DIRECT FROM AUDIO):\n")
                f.write(tanglish_tamil_text)
                f.write("\n\nENGLISH TRANSLATION:\n")
                f.write(english_text)
                f.write("\n\nTANGLISH IN ENGLISH TEXT:\n")
                f.write(tanglish_english_text)
                f.write("\n\nTAMIL TEXT (FROM ENGLISH):\n")
                f.write(tamil_text)
            
            # Complete
            broadcast_status_update(upload_id, {
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
            })
            
        except Exception as e:
            broadcast_status_update(upload_id, {
                'status': 'error',
                'progress': 0,
                'message': f'Processing failed: {str(e)}'
            })
            print(f"Full error details: {e}")
            import traceback
            traceback.print_exc()

def process_video_batch_mode(upload_id, app):
    """
    Alternative processing function using batch transcription for even better efficiency
    """
    with app.app_context():
        try:
            # Initial setup (same as above)
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
            files = os.listdir(upload_dir)
            video_files = [f for f in files if allowed_file(f, current_app.config['ALLOWED_EXTENSIONS'])]
            video_path = os.path.join(upload_dir, video_files[0])
            
            # Audio extraction steps (same as above)
            broadcast_status_update(upload_id, {'status': 'processing', 'progress': 10, 'message': 'Extracting audio...'})
            
            audio_path = os.path.join(upload_dir, "extracted_audio.mp3")
            wav_audio_path = os.path.join(upload_dir, "audio_for_speech.wav")
            
            extract_audio_from_video(video_path, audio_path)
            convert_audio_format(audio_path, wav_audio_path)
            
            # Batch transcription for both Tamil and English at once
            broadcast_status_update(upload_id, {'status': 'processing', 'progress': 30, 'message': 'Transcribing in multiple languages...'})
            
            # This uses a single model instance for both languages
            batch_results = batch_transcribe_multiple_languages(
                wav_audio_path, 
                languages=["ta", "en"], 
                model_size="base"
            )
            
            pure_tamil_text = batch_results.get("ta", "")
            english_text = batch_results.get("en", "")
            
            broadcast_status_update(upload_id, {'status': 'processing', 'progress': 70, 'message': 'Multi-language transcription completed'})
            
            # Continue with other processing steps...
            # (Tanglish conversion, standard Tamil translation, SRT generation)
            
        except Exception as e:
            broadcast_status_update(upload_id, {
                'status': 'error',
                'progress': 0,
                'message': f'Batch processing failed: {str(e)}'
            })

@api_bp.route('/process/<upload_id>', methods=['POST'])
def process_video(upload_id):
    """
    Endpoint to start processing an uploaded video
    Now uses unified Whisper functions for better efficiency
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
        
        # Start async processing with unified Whisper functions
        thread = threading.Thread(
            target=process_video_async, 
            args=(upload_id, current_app._get_current_object())
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'processing_started',
            'upload_id': upload_id,
            'message': 'Video processing started with optimized AI models. Connect to /status-stream endpoint for real-time updates.'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@api_bp.route('/process-batch/<upload_id>', methods=['POST'])
def process_video_batch(upload_id):
    """
    Alternative endpoint for batch processing mode
    """
    try:
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
        if not os.path.exists(upload_dir):
            return jsonify({'error': 'Invalid upload ID'}), 404
        
        thread = threading.Thread(
            target=process_video_batch_mode, 
            args=(upload_id, current_app._get_current_object())
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'batch_processing_started',
            'upload_id': upload_id,
            'message': 'Batch processing started for maximum efficiency.'
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}, 500)

@api_bp.route('/status-stream/<upload_id>')
def status_stream(upload_id):
    """
    Server-Sent Events endpoint for real-time status updates
    """
    def event_generator():
        # Create a queue for this client
        client_queue = queue.Queue()
        
        # Register this client for the upload_id
        sse_clients[upload_id].append(client_queue)
        
        try:
            # Send current status immediately if available
            if upload_id in processing_status:
                current_status = processing_status[upload_id]
                yield f"data: {json.dumps(current_status)}\n\n"
            
            # Listen for updates
            while True:
                try:
                    # Wait for status update (with timeout to send keepalive)
                    status_data = client_queue.get(timeout=30)
                    yield f"data: {json.dumps(status_data)}\n\n"
                    
                    # If processing is complete or failed, close the connection
                    if status_data.get('status') in ['completed', 'error']:
                        break
                        
                except queue.Empty:
                    # Send keepalive
                    yield f"data: {json.dumps({'keepalive': True})}\n\n"
                    
        except GeneratorExit:
            # Client disconnected
            pass
        finally:
            # Remove client from list
            if client_queue in sse_clients[upload_id]:
                sse_clients[upload_id].remove(client_queue)
    
    return Response(
        event_generator(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Cache-Control'
        }
    )

@api_bp.route('/status/<upload_id>', methods=['GET'])
def get_processing_status(upload_id):
    """
    Endpoint to check processing status (fallback for non-SSE clients)
    """
    if upload_id not in processing_status:
        return jsonify({'error': 'No processing found for this upload ID'}), 404
    
    return jsonify(processing_status[upload_id])

# ... (rest of the endpoints remain the same)
@api_bp.route('/download/<upload_id>', methods=['GET'])
def download_results(upload_id):
    """
    Endpoint to download the results text file
    """
    try:
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
            'tanglish_tamil': 'tanglish_tamil_subtitles.srt',
            'tanglish_english': 'tanglish_english_subtitles.srt'
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
        
        # Remove from processing status and SSE clients
        if upload_id in processing_status:
            del processing_status[upload_id]
        if upload_id in sse_clients:
            del sse_clients[upload_id]
        
        return jsonify({
            'status': 'success',
            'message': 'Temporary files cleaned up successfully'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500