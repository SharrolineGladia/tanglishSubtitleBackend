import os
import re
import time
import speech_recognition as sr
from datetime import datetime, timedelta
from faster_whisper import WhisperModel
from pydub import AudioSegment
import moviepy.editor as mp
from api.services.tanglish_service import contains_tamil_script, filter_non_tamil_words

# Global model instances to avoid reloading
_whisper_models = {}

def get_whisper_model(model_size="base", device="cpu", compute_type="int8"):
    """Get or create Whisper model instance with caching"""
    global _whisper_models
    model_key = f"{model_size}_{device}_{compute_type}"
    
    if model_key not in _whisper_models:
        print(f"Loading Whisper model: {model_size}")
        _whisper_models[model_key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    
    return _whisper_models[model_key]

def format_timestamp(seconds):
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)"""
    seconds = max(0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

def get_video_duration(video_path):
    """Get video duration in seconds"""
    try:
        with mp.VideoFileClip(video_path) as video:
            return video.duration
    except Exception as e:
        print(f"Error getting video duration: {e}")
        return None

def get_audio_video_offset(video_path, audio_path):
    """Calculate any offset between extracted audio and video"""
    try:
        video_duration = get_video_duration(video_path)
        audio = AudioSegment.from_file(audio_path)
        audio_duration = len(audio) / 1000.0
        
        offset = abs(video_duration - audio_duration) if video_duration else 0
        print(f"Video duration: {video_duration}s, Audio duration: {audio_duration}s, Offset: {offset}s")
        
        return min(offset, 0.5)  # Cap offset at 0.5 seconds
        
    except Exception as e:
        print(f"Error calculating audio-video offset: {e}")
        return 0

def transcribe_tamil_audio_hybrid(audio_path, model=None):
    """
    Hybrid transcription using both Google Speech Recognition and Whisper
    """
    recognizer = sr.Recognizer()
    tamil_text = ""
    
    # Try Google Speech Recognition first
    try:
        with sr.AudioFile(audio_path) as source:
            recognizer.adjust_for_ambient_noise(source, duration=1.0)
            audio_data = recognizer.record(source)
        
        tamil_text = recognizer.recognize_google(audio_data, language="ta-IN")
        print(f"Google Speech Recognition successful: {len(tamil_text)} characters")
    except Exception as e:
        print(f"Google Speech Recognition error: {str(e)}")
    
    # Use Whisper fallback if Google fails or result is too short
    if not tamil_text or len(tamil_text.strip()) < 10:
        try:
            if model is None:
                model = get_whisper_model("base")
            
            segments, _ = model.transcribe(audio_path, language="ta", beam_size=5)
            whisper_text = " ".join([seg.text for seg in segments])
            
            # Use Whisper result if it's better
            if len(whisper_text.strip()) > len(tamil_text.strip()):
                tamil_text = whisper_text
                print(f"Whisper transcription used: {len(tamil_text)} characters")
                
        except Exception as e:
            print(f"Whisper transcription error: {str(e)}")
    
    return tamil_text

def transcribe_with_whisper(audio_path, language="ta", model_size="base", **kwargs):
    """
    Enhanced Whisper transcription with flexible parameters
    """
    try:
        model = get_whisper_model(model_size)
        
        # Default parameters
        transcribe_params = {
            'language': language,
            'beam_size': 5,
            **kwargs  # Allow override of default parameters
        }
        
        segments, info = model.transcribe(audio_path, **transcribe_params)
        text = " ".join([seg.text for seg in segments])
        
        # Special handling for Tamil
        if language == "ta":
            if not contains_tamil_script(text):
                # Retry once if no Tamil script detected
                print("No Tamil script detected, retrying...")
                segments, _ = model.transcribe(audio_path, language="ta", beam_size=5)
                text = " ".join([seg.text for seg in segments])
            
            # Filter non-Tamil words
            filtered_text = filter_non_tamil_words(text)
            return filtered_text if filtered_text else text
        
        return text
        
    except Exception as e:
        print(f"Error with Whisper transcription: {e}")
        return ""

def transcribe_tamil_from_chunks(audio_chunks, model=None):
    """
    Process multiple audio chunks for Tamil transcription
    """
    all_tamil_text = ""
    
    if model is None:
        model = get_whisper_model("base")
    
    for i, chunk_path in enumerate(audio_chunks):
        print(f"Processing Tamil chunk {i+1}/{len(audio_chunks)}...")
        
        # Use hybrid approach for better results
        chunk_text = transcribe_tamil_audio_hybrid(chunk_path, model=model)
        
        # Apply filtering
        filtered_text = filter_non_tamil_words(chunk_text)
        if len(filtered_text) < len(chunk_text) * 0.5:
            all_tamil_text += " " + chunk_text
        else:
            all_tamil_text += " " + filtered_text
    
    return all_tamil_text.strip()

def process_pure_tamil_from_audio(audio_chunks, model=None):
    """
    Process audio chunks to extract pure Tamil text with fallback strategies
    """
    if model is None:
        model = get_whisper_model("base")
    
    # First attempt: Process chunks individually
    pure_tamil_text = transcribe_tamil_from_chunks(audio_chunks, model=model)
    
    # Fallback: Combine chunks and process as one if no Tamil script detected
    if not contains_tamil_script(pure_tamil_text):
        try:
            print("No Tamil script detected in chunks, trying combined audio...")
            combined_audio = AudioSegment.empty()
            
            for chunk_path in audio_chunks:
                chunk = AudioSegment.from_file(chunk_path)
                combined_audio += chunk
            
            combined_path = os.path.join(os.path.dirname(audio_chunks[0]), "combined_for_tamil.wav")
            combined_audio.export(combined_path, format="wav")
            
            # Use hybrid transcription on combined audio
            pure_tamil_text = transcribe_tamil_audio_hybrid(combined_path, model=model)
            
            # Cleanup
            if os.path.exists(combined_path):
                os.remove(combined_path)
                
        except Exception as e:
            print(f"Enhanced combined transcription failed: {e}")
    
    return pure_tamil_text

def generate_precise_timed_segments(audio_path, video_path, language="ta", model_size="base"):
    """
    Generate precise timed segments using Whisper with video synchronization
    """
    try:
        model = get_whisper_model(model_size)
        
        # Calculate any audio-video offset
        av_offset = get_audio_video_offset(video_path, audio_path)
        
        print(f"Generating precise timing for language: {language}")
        
        # Use optimal parameters for precise timing
        segments, info = model.transcribe(
            audio_path, 
            language=language, 
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=200,
                speech_pad_ms=50
            ),
            beam_size=3,
            best_of=3,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.4,
            initial_prompt=None
        )
        
        timed_segments = []
        min_segment_duration = 0.8
        max_segment_duration = 6.0
        
        for segment in segments:
            duration = segment.end - segment.start
            
            # Skip very short segments
            if duration < min_segment_duration:
                continue
            
            # Clean up the text
            text = segment.text.strip()
            if not text or len(text) < 2:
                continue
            
            # Apply audio-video offset correction
            start_time = max(0, segment.start - av_offset)
            end_time = segment.end - av_offset
            
            # Ensure reasonable duration bounds
            if end_time - start_time > max_segment_duration:
                end_time = start_time + max_segment_duration
            
            timed_segments.append({
                'start': start_time,
                'end': end_time,
                'text': text,
                'confidence': getattr(segment, 'avg_logprob', 0),
                'word_count': len(text.split())
            })
        
        # Sort by start time
        timed_segments.sort(key=lambda x: x['start'])
        
        # Post-process to fix overlaps and ensure proper gaps
        cleaned_segments = []
        min_gap = 0.1
        
        for i, segment in enumerate(timed_segments):
            if i == 0:
                cleaned_segments.append(segment)
                continue
            
            prev_segment = cleaned_segments[-1]
            
            # Fix overlaps
            if segment['start'] <= prev_segment['end']:
                new_start = prev_segment['end'] + min_gap
                
                if segment['end'] - new_start < min_segment_duration:
                    # Extend previous segment
                    prev_segment['end'] = segment['end']
                    prev_segment['text'] += " " + segment['text']
                    continue
                else:
                    segment['start'] = new_start
            
            cleaned_segments.append(segment)
        
        print(f"Generated {len(cleaned_segments)} precise timed segments")
        
        # Debug: Show first few segments
        for i, seg in enumerate(cleaned_segments[:3]):
            print(f"  Segment {i+1}: {seg['start']:.2f}s-{seg['end']:.2f}s ({seg['end']-seg['start']:.2f}s): '{seg['text'][:40]}...'")
        
        return cleaned_segments
    
    except Exception as e:
        print(f"Error getting precise timed segments: {e}")
        import traceback
        traceback.print_exc()
        return []

def transcribe_audio_with_timestamps(audio_path, language="ta", model_size="base"):
    """
    Transcribe audio with detailed timestamp information
    Returns both text and timing segments
    """
    model = get_whisper_model(model_size)
    
    try:
        segments, info = model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            beam_size=5
        )
        
        text_segments = []
        full_text = ""
        
        for segment in segments:
            segment_data = {
                'start': segment.start,
                'end': segment.end,
                'text': segment.text.strip()
            }
            text_segments.append(segment_data)
            full_text += segment.text
        
        # Apply language-specific filtering
        if language == "ta":
            full_text = filter_non_tamil_words(full_text)
        
        return {
            'text': full_text.strip(),
            'segments': text_segments,
            'language': language
        }
        
    except Exception as e:
        print(f"Error in timestamped transcription: {e}")
        return {
            'text': "",
            'segments': [],
            'language': language
        }

def batch_transcribe_multiple_languages(audio_path, languages=["ta", "en"], model_size="base"):
    """
    Transcribe audio in multiple languages using a single model instance
    """
    model = get_whisper_model(model_size)
    results = {}
    
    for lang in languages:
        print(f"Transcribing in {lang}...")
        try:
            if lang == "ta":
                # Use hybrid approach for Tamil
                results[lang] = transcribe_tamil_audio_hybrid(audio_path, model)
            else:
                # Use standard Whisper for other languages
                segments, _ = model.transcribe(audio_path, language=lang, beam_size=5)
                results[lang] = " ".join([seg.text for seg in segments])
                
        except Exception as e:
            print(f"Error transcribing {lang}: {e}")
            results[lang] = ""
    
    return results

# Utility functions for backward compatibility
def get_model():
    """Backward compatibility function"""
    return get_whisper_model("base")

def cleanup_models():
    """Clean up loaded models to free memory"""
    global _whisper_models
    _whisper_models.clear()
    print("Whisper models cleared from memory")