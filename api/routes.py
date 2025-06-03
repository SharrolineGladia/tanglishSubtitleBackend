from flask import Blueprint, request, jsonify, current_app, Response
import io
import uuid
import time
import zipfile
import threading
import json
import tempfile
import os
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
from api.services.translation_service import translate_text
from api.services.tanglish_service import tamil_to_tanglish, contains_tamil_script
from api.services.srt_service import generate_all_srt_files_improved
from utils.file_utils import allowed_file

api_bp = Blueprint('api', __name__)

# In-memory storage for processing results and files
processing_status = {}
processing_results = {}  # upload_id -> {'results': {...}, 'files': {...}}
sse_clients = defaultdict(list)
file_cache = defaultdict(dict)  # upload_id -> {filename: BytesIO}

# Configuration
MAX_CACHE_SIZE = 100 * 1024 * 1024  # 100MB max cache per upload
CACHE_EXPIRY = 3600  # 1 hour expiry

class InMemoryFileManager:
    """Manages files in memory with automatic cleanup"""
    
    def __init__(self):
        self.files = {}  # upload_id -> {filename: {'data': BytesIO, 'timestamp': float, 'size': int}}
        self.total_size = 0
        self.max_size = 500 * 1024 * 1024  # 500MB total cache
    
    def store_file(self, upload_id, filename, data):
        """Store file data in memory"""
        if isinstance(data, str):
            data = data.encode('utf-8')
        if isinstance(data, bytes):
            data = io.BytesIO(data)
        elif hasattr(data, 'read'):
            # File-like object
            content = data.read()
            data = io.BytesIO(content)
        
        file_size = len(data.getvalue())
        
        # Check if we need to cleanup old files
        if self.total_size + file_size > self.max_size:
            self._cleanup_old_files()
        
        if upload_id not in self.files:
            self.files[upload_id] = {}
        
        self.files[upload_id][filename] = {
            'data': data,
            'timestamp': time.time(),
            'size': file_size
        }
        self.total_size += file_size
        
        return True
    
    def get_file(self, upload_id, filename):
        """Retrieve file data from memory"""
        if upload_id in self.files and filename in self.files[upload_id]:
            file_info = self.files[upload_id][filename]
            file_info['data'].seek(0)  # Reset to beginning
            return file_info['data']
        return None
    
    def list_files(self, upload_id):
        """List all files for an upload"""
        if upload_id in self.files:
            return list(self.files[upload_id].keys())
        return []
    
    def delete_upload(self, upload_id):
        """Delete all files for an upload"""
        if upload_id in self.files:
            for file_info in self.files[upload_id].values():
                self.total_size -= file_info['size']
            del self.files[upload_id]
    
    def _cleanup_old_files(self):
        """Remove old files to free up memory"""
        current_time = time.time()
        uploads_to_remove = []
        
        for upload_id, files in self.files.items():
            upload_age = min(file_info['timestamp'] for file_info in files.values())
            if current_time - upload_age > CACHE_EXPIRY:
                uploads_to_remove.append(upload_id)
        
        for upload_id in uploads_to_remove:
            self.delete_upload(upload_id)

# Global file manager instance
file_manager = InMemoryFileManager()

def broadcast_status_update(upload_id, status_data):
    """Broadcast status update to all SSE clients for this upload_id"""
    processing_status[upload_id] = status_data
    
    if upload_id in sse_clients:
        disconnected_clients = []
        for client_queue in sse_clients[upload_id]:
            try:
                client_queue.put(status_data, timeout=1)
            except:
                disconnected_clients.append(client_queue)
        
        for client in disconnected_clients:
            sse_clients[upload_id].remove(client)

def process_file_in_memory(file_data, filename):
    """Process uploaded file entirely in memory using temporary files"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as temp_file:
        temp_file.write(file_data)
        temp_file.flush()
        temp_path = temp_file.name
    
    try:
        return temp_path
    except:
        # Cleanup on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

def process_video_streaming(upload_id, file_data, filename, app):
    """Process video entirely in memory with streaming results"""
    with app.app_context():
        temp_files = []  # Keep track for cleanup
        
        try:
            broadcast_status_update(upload_id, {
                'status': 'processing', 
                'progress': 0, 
                'message': 'Starting processing...'
            })
            
            # Step 1: Create temporary file for video processing
            video_temp = process_file_in_memory(file_data, filename)
            temp_files.append(video_temp)
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 10,
                'message': 'Extracting audio from video...'
            })
            
            # Step 2: Extract audio to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as audio_temp:
                audio_path = audio_temp.name
                temp_files.append(audio_path)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as wav_temp:
                wav_path = wav_temp.name
                temp_files.append(wav_path)
            
            extract_audio_from_video(video_temp, audio_path)
            convert_audio_format(audio_path, wav_path)
            
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 20,
                'message': 'Audio extraction completed'
            })
            
            # Step 3: Split audio for processing
            broadcast_status_update(upload_id, {
                'status': 'processing',
                'progress': 25,
                'message': 'Preparing audio chunks...'
            })
            
            # Create temporary directory for chunks
            with tempfile.TemporaryDirectory() as temp_dir:
                chunks = split_audio(wav_path, chunk_length_ms=15000, output_dir=temp_dir)
                
                broadcast_status_update(upload_id, {
                    'status': 'processing',
                    'progress': 30,
                    'message': 'Audio chunks prepared'
                })
                
                # Step 4: Load Whisper model
                broadcast_status_update(upload_id, {
                    'status': 'processing',
                    'progress': 32,
                    'message': 'Loading AI models...'
                })
                
                whisper_model = get_whisper_model("base")
                
                # Step 5: Process Tamil transcription
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
                
                # Step 6: Generate Tanglish
                broadcast_status_update(upload_id, {
                    'status': 'processing',
                    'progress': 55,
                    'message': 'Converting to Tanglish...'
                })
                
                if contains_tamil_script(tanglish_tamil_text):
                    tanglish_english_text = tamil_to_tanglish(tanglish_tamil_text)
                else:
                    tanglish_english_text = "Tamil transcription failed"
                
                # Step 7: English transcription
                broadcast_status_update(upload_id, {
                    'status': 'processing',
                    'progress': 65,
                    'message': 'Generating English translation...'
                })
                
                try:
                    english_text = transcribe_with_whisper(wav_path, language="en")
                except Exception as e:
                    print(f"English transcription failed: {e}")
                    english_text = translate_text(tanglish_tamil_text, "ta", "en") if tanglish_tamil_text else ""
                
                # Step 8: Standard Tamil translation
                broadcast_status_update(upload_id, {
                    'status': 'processing',
                    'progress': 75,
                    'message': 'Generating standard Tamil translation...'
                })
                
                tamil_text = translate_text(english_text, "en", "ta") if english_text else ""
                
                # Step 9: Generate results and store in memory
                broadcast_status_update(upload_id, {
                    'status': 'processing',
                    'progress': 85,
                    'message': 'Generating results...'
                })
                
                results = {
                    'tanglish_tamil': tanglish_tamil_text,
                    'english': english_text,
                    'tanglish_english': tanglish_english_text,
                    'tamil': tamil_text
                }
                
                # Store results text file in memory
                results_content = f"""===== TRANSCRIPTION RESULTS =====

TANGLISH IN TAMIL TEXT (DIRECT FROM AUDIO):
{tanglish_tamil_text}

ENGLISH TRANSLATION:
{english_text}

TANGLISH IN ENGLISH TEXT:
{tanglish_english_text}

TAMIL TEXT (FROM ENGLISH):
{tamil_text}
"""
                
                file_manager.store_file(upload_id, "results.txt", results_content)
                
                # Generate SRT files in memory
                broadcast_status_update(upload_id, {
                    'status': 'processing',
                    'progress': 90,
                    'message': 'Generating subtitle files...'
                })
                
                # Generate SRT content for each language
                srt_files = {}
                
                # Simple SRT generation (you can enhance this)
                def generate_simple_srt(text, language_name):
                    lines = text.split('. ')
                    srt_content = ""
                    for i, line in enumerate(lines):
                        if line.strip():
                            start_time = i * 2
                            end_time = (i + 1) * 2
                            srt_content += f"{i+1}\n"
                            srt_content += f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}\n"
                            srt_content += f"{line.strip()}\n\n"
                    return srt_content
                
                def format_srt_time(seconds):
                    hours = seconds // 3600
                    minutes = (seconds % 3600) // 60
                    secs = seconds % 60
                    return f"{hours:02d}:{minutes:02d}:{secs:02d},000"
                
                if tanglish_tamil_text:
                    srt_content = generate_simple_srt(tanglish_tamil_text, "Tanglish Tamil")
                    file_manager.store_file(upload_id, "tanglish_tamil_subtitles.srt", srt_content)
                    srt_files['tanglish_tamil'] = 'tanglish_tamil_subtitles.srt'
                
                if english_text:
                    srt_content = generate_simple_srt(english_text, "English")
                    file_manager.store_file(upload_id, "english_subtitles.srt", srt_content)
                    srt_files['english'] = 'english_subtitles.srt'
                
                if tanglish_english_text:
                    srt_content = generate_simple_srt(tanglish_english_text, "Tanglish English")
                    file_manager.store_file(upload_id, "tanglish_english_subtitles.srt", srt_content)
                    srt_files['tanglish_english'] = 'tanglish_english_subtitles.srt'
                
                if tamil_text:
                    srt_content = generate_simple_srt(tamil_text, "Tamil")
                    file_manager.store_file(upload_id, "tamil_subtitles.srt", srt_content)
                    srt_files['tamil'] = 'tamil_subtitles.srt'
                
                # Store processing results
                processing_results[upload_id] = {
                    'results': results,
                    'srt_files': srt_files,
                    'timestamp': time.time()
                }
                
                # Complete
                broadcast_status_update(upload_id, {
                    'status': 'completed',
                    'progress': 100,
                    'message': 'Processing completed successfully',
                    'results': results,
                    'srt_files': srt_files,
                    'srt_count': len(srt_files)
                })
        
        except Exception as e:
            broadcast_status_update(upload_id, {
                'status': 'error',
                'progress': 0,
                'message': f'Processing failed: {str(e)}'
            })
            print(f"Processing error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # Clean up temporary files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                except Exception as e:
                    print(f"Cleanup error: {e}")

@api_bp.route('/upload', methods=['POST'])
def upload_video():
    """Upload and immediately start processing video in memory"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename, current_app.config['ALLOWED_EXTENSIONS']):
        upload_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        
        # Read file data into memory
        file_data = file.read()
        
        # Start processing immediately
        thread = threading.Thread(
            target=process_video_streaming,
            args=(upload_id, file_data, filename, current_app._get_current_object())
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'success',
            'upload_id': upload_id,
            'filename': filename,
            'message': 'Video uploaded and processing started'
        })
    
    return jsonify({'error': 'File type not allowed'}), 400

@api_bp.route('/status-stream/<upload_id>')
def status_stream(upload_id):
    """Server-Sent Events endpoint for real-time status updates"""
    def event_generator():
        client_queue = queue.Queue()
        sse_clients[upload_id].append(client_queue)
        
        try:
            if upload_id in processing_status:
                current_status = processing_status[upload_id]
                yield f"data: {json.dumps(current_status)}\n\n"
            
            while True:
                try:
                    status_data = client_queue.get(timeout=30)
                    yield f"data: {json.dumps(status_data)}\n\n"
                    
                    if status_data.get('status') in ['completed', 'error']:
                        break
                        
                except queue.Empty:
                    yield f"data: {json.dumps({'keepalive': True})}\n\n"
                    
        except GeneratorExit:
            pass
        finally:
            if client_queue in sse_clients[upload_id]:
                sse_clients[upload_id].remove(client_queue)
    
    return Response(
        event_generator(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*'
        }
    )

@api_bp.route('/status/<upload_id>', methods=['GET'])
def get_processing_status(upload_id):
    """Get current processing status"""
    if upload_id not in processing_status:
        return jsonify({'error': 'No processing found for this upload ID'}), 404
    
    return jsonify(processing_status[upload_id])

@api_bp.route('/download/<upload_id>', methods=['GET'])
def download_results(upload_id):
    """Download results text file from memory"""
    file_data = file_manager.get_file(upload_id, "results.txt")
    
    if not file_data:
        return jsonify({'error': 'Results file not found'}), 404
    
    return Response(
        file_data.getvalue(),
        mimetype='text/plain',
        headers={
            'Content-Disposition': 'attachment; filename=tamil_transcription_results.txt'
        }
    )

@api_bp.route('/download-srt/<upload_id>/<srt_type>', methods=['GET'])
def download_srt(upload_id, srt_type):
    """Download individual SRT files from memory"""
    srt_filenames = {
        'tanglish_tamil': 'tanglish_tamil_subtitles.srt',
        'english': 'english_subtitles.srt',
        'tanglish_english': 'tanglish_english_subtitles.srt',
        'tamil': 'tamil_subtitles.srt'
    }
    
    if srt_type not in srt_filenames:
        return jsonify({'error': 'Invalid SRT type'}), 400
    
    filename = srt_filenames[srt_type]
    file_data = file_manager.get_file(upload_id, filename)
    
    if not file_data:
        return jsonify({'error': f'{srt_type.title()} SRT file not found'}), 404
    
    return Response(
        file_data.getvalue(),
        mimetype='application/x-subrip',
        headers={
            'Content-Disposition': f'attachment; filename={filename}'
        }
    )

@api_bp.route('/download-all-srt/<upload_id>', methods=['GET'])
def download_all_srt(upload_id):
    """Download all SRT files as a ZIP archive from memory"""
    if upload_id not in processing_results:
        return jsonify({'error': 'No results found for this upload ID'}), 404
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        files_added = 0
        
        # Add SRT files
        srt_files = [
            'tanglish_tamil_subtitles.srt',
            'english_subtitles.srt',
            'tanglish_english_subtitles.srt',
            'tamil_subtitles.srt'
        ]
        
        for filename in srt_files:
            file_data = file_manager.get_file(upload_id, filename)
            if file_data:
                zipf.writestr(filename, file_data.getvalue())
                files_added += 1
        
        # Add results file
        results_data = file_manager.get_file(upload_id, "results.txt")
        if results_data:
            zipf.writestr("transcription_results.txt", results_data.getvalue())
            files_added += 1
    
    if files_added == 0:
        return jsonify({'error': 'No files found'}), 404
    
    zip_buffer.seek(0)
    
    return Response(
        zip_buffer.getvalue(),
        mimetype='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename=subtitles_{upload_id[:8]}.zip'
        }
    )

@api_bp.route('/list-files/<upload_id>', methods=['GET'])
def list_files(upload_id):
    """List all available files for an upload from memory"""
    files = file_manager.list_files(upload_id)
    
    if not files:
        return jsonify({'error': 'No files found for this upload ID'}), 404
    
    available_files = {
        'srt_files': [f for f in files if f.endswith('.srt')],
        'text_files': [f for f in files if f.endswith('.txt')],
        'all_files': files
    }
    
    return jsonify({
        'status': 'success',
        'upload_id': upload_id,
        'files': available_files
    })

@api_bp.route('/cleanup/<upload_id>', methods=['DELETE'])
def cleanup(upload_id):
    """Clean up memory for an upload"""
    file_manager.delete_upload(upload_id)
    
    if upload_id in processing_status:
        del processing_status[upload_id]
    if upload_id in processing_results:
        del processing_results[upload_id]
    if upload_id in sse_clients:
        del sse_clients[upload_id]
    
    return jsonify({
        'status': 'success',
        'message': 'Upload data cleaned up successfully'
    })

# Periodic cleanup task
def periodic_cleanup():
    """Clean up expired uploads periodically"""
    while True:
        try:
            file_manager._cleanup_old_files()
            
            # Clean up expired processing status
            current_time = time.time()
            expired_uploads = []
            
            for upload_id, result_data in processing_results.items():
                if current_time - result_data.get('timestamp', 0) > CACHE_EXPIRY:
                    expired_uploads.append(upload_id)
            
            for upload_id in expired_uploads:
                if upload_id in processing_results:
                    del processing_results[upload_id]
                if upload_id in processing_status:
                    del processing_status[upload_id]
                if upload_id in sse_clients:
                    del sse_clients[upload_id]
            
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        time.sleep(300)  # Run every 5 minutes

# Start cleanup thread
cleanup_thread = threading.Thread(target=periodic_cleanup)
cleanup_thread.daemon = True
cleanup_thread.start()