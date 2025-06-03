# api/services/srt_service.py - Fixed version with accurate video synchronization

import os
import re
from datetime import datetime, timedelta
from faster_whisper import WhisperModel
from pydub import AudioSegment
import moviepy.editor as mp

from api.services.whisper_functions import (
    get_whisper_model,
    format_timestamp,
    get_video_duration,
    get_audio_video_offset,
    generate_precise_timed_segments
)

def split_text_into_segments(text, max_chars=60, max_words=8):
    """Split long text into smaller segments for subtitles with better readability"""
    if not text:
        return []
    
    # Clean the text
    text = text.strip()
    if not text:
        return []
    
    # Split by sentences first, handling multiple punctuation
    sentences = re.split(r'[.!?।]+(?:\s|$)', text)  # Added Tamil punctuation
    segments = []
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        # If sentence is short enough, use as is
        if len(sentence) <= max_chars and len(sentence.split()) <= max_words:
            segments.append(sentence)
        else:
            # Split by phrases/clauses first
            phrases = re.split(r'[,;:\n]', sentence)
            
            current_segment = ""
            for phrase in phrases:
                phrase = phrase.strip()
                if not phrase:
                    continue
                    
                test_segment = current_segment + " " + phrase if current_segment else phrase
                
                if len(test_segment) <= max_chars and len(test_segment.split()) <= max_words:
                    current_segment = test_segment
                else:
                    if current_segment:
                        segments.append(current_segment)
                    
                    # If phrase itself is too long, split by words
                    if len(phrase) > max_chars or len(phrase.split()) > max_words:
                        words = phrase.split()
                        word_segment = ""
                        
                        for word in words:
                            test_word_segment = word_segment + " " + word if word_segment else word
                            
                            if len(test_word_segment) <= max_chars and len(test_word_segment.split()) <= max_words:
                                word_segment = test_word_segment
                            else:
                                if word_segment:
                                    segments.append(word_segment)
                                word_segment = word
                        
                        if word_segment:
                            current_segment = word_segment
                    else:
                        current_segment = phrase
            
            if current_segment:
                segments.append(current_segment)
    
    return [seg.strip() for seg in segments if seg.strip()]


def create_smart_fallback_segments(audio_path, video_path, text):
    """Create segments with smart estimated timing when Whisper fails"""
    try:
        print("Creating smart fallback timing...")
        
        # Get accurate duration
        video_duration = get_video_duration(video_path)
        if not video_duration:
            audio = AudioSegment.from_file(audio_path)
            video_duration = len(audio) / 1000.0
        
        segments = split_text_into_segments(text, max_chars=60, max_words=8)
        if not segments:
            return []
        
        print(f"Split into {len(segments)} text segments for {video_duration:.1f}s video")
        
        # Calculate timing based on speech patterns
        total_chars = sum(len(seg) for seg in segments)
        total_words = sum(len(seg.split()) for seg in segments)
        
        # Estimate speech rate (characters per second)
        # Tamil speech is typically slower than English
        is_tamil = any(ord(c) > 127 for c in text[:100])  # Check for Tamil characters
        
        if is_tamil:
            chars_per_second = 6  # Slower for Tamil
            words_per_second = 2.5
        else:
            chars_per_second = 10  # Faster for English/Tanglish
            words_per_second = 3.5
        
        # Calculate individual segment timings
        timed_segments = []
        current_time = 0.2  # Small initial offset
        
        # Reserve some time at the end
        usable_duration = video_duration * 0.95
        
        for i, segment_text in enumerate(segments):
            char_count = len(segment_text)
            word_count = len(segment_text.split())
            
            # Calculate duration based on content
            char_duration = char_count / chars_per_second
            word_duration = word_count / words_per_second
            
            # Use the longer estimate for safety
            estimated_duration = max(char_duration, word_duration)
            
            # Apply bounds
            min_duration = max(1.2, word_count * 0.4)  # Minimum based on word count
            max_duration = min(5.0, char_count * 0.15)  # Maximum based on character count
            
            duration = max(min_duration, min(max_duration, estimated_duration))
            
            # Calculate end time
            end_time = current_time + duration
            
            # Ensure we don't exceed video duration
            if end_time > usable_duration:
                end_time = usable_duration
                if end_time <= current_time + 1.0:  # If less than 1 second left, stop
                    break
            
            timed_segments.append({
                'start': current_time,
                'end': end_time,
                'text': segment_text,
                'confidence': 0.3  # Lower confidence for fallback
            })
            
            # Move to next segment with small gap
            current_time = end_time + 0.15
            
            # Stop if we're running out of time
            if current_time >= usable_duration:
                break
        
        # If we have remaining segments, compress timing proportionally
        if len(timed_segments) < len(segments):
            print(f"Warning: Only fit {len(timed_segments)}/{len(segments)} segments in video duration")
        
        print(f"Created {len(timed_segments)} smart fallback segments")
        return timed_segments
    
    except Exception as e:
        print(f"Error creating smart fallback segments: {e}")
        return []

def create_srt_content(timed_segments):
    """Create SRT file content from timed segments"""
    if not timed_segments:
        return ""
    
    srt_content = ""
    subtitle_index = 1
    
    for segment in timed_segments:
        start_time = format_timestamp(segment['start'])
        end_time = format_timestamp(segment['end'])
        text = segment['text'].strip()
        
        if not text:  # Skip empty segments
            continue
        
        # Ensure proper line breaks for long text (max 2 lines)
        if len(text) > 50:
            words = text.split()
            if len(words) > 6:
                # Find best break point (try to split at middle)
                mid_point = len(words) // 2
                # Adjust break point to avoid breaking at conjunctions
                break_words = ['and', 'or', 'but', 'so', 'மற்றும்', 'அல்லது', 'ஆனால்']
                
                for i in range(max(1, mid_point-2), min(len(words)-1, mid_point+3)):
                    if words[i-1].lower() not in break_words and words[i].lower() not in break_words:
                        mid_point = i
                        break
                
                line1 = ' '.join(words[:mid_point])
                line2 = ' '.join(words[mid_point:])
                
                # Ensure neither line is too long
                if len(line1) <= 35 and len(line2) <= 35:
                    text = f"{line1}\n{line2}"
        
        srt_content += f"{subtitle_index}\n"
        srt_content += f"{start_time} --> {end_time}\n"
        srt_content += f"{text}\n\n"
        
        subtitle_index += 1
    
    return srt_content

def align_text_to_timing(base_timed_segments, new_text, language_hint=""):
    """Align new text to existing timing segments with better accuracy"""
    if not base_timed_segments or not new_text:
        return []
    
    print(f"Aligning text to {len(base_timed_segments)} timing segments")
    
    # Split new text more conservatively for better alignment
    max_chars = 50 if language_hint in ['ta', 'tamil'] else 60
    max_words = 6 if language_hint in ['ta', 'tamil'] else 8
    
    new_segments = split_text_into_segments(new_text, max_chars=max_chars, max_words=max_words)
    
    if not new_segments:
        return []
    
    print(f"New text split into {len(new_segments)} segments")
    
    aligned_segments = []
    
    # Get timing boundaries
    total_start_time = base_timed_segments[0]['start']
    total_end_time = base_timed_segments[-1]['end']
    total_duration = total_end_time - total_start_time
    
    if len(new_segments) == len(base_timed_segments):
        # Perfect match - use original timing
        print("Using original timing (1:1 mapping)")
        for i, base_seg in enumerate(base_timed_segments):
            aligned_segments.append({
                'start': base_seg['start'],
                'end': base_seg['end'],
                'text': new_segments[i]
            })
    
    elif len(new_segments) < len(base_timed_segments):
        # Fewer new segments - merge timing segments
        print("Merging timing segments")
        
        segments_per_new = len(base_timed_segments) / len(new_segments)
        
        for i, new_text_seg in enumerate(new_segments):
            start_idx = int(i * segments_per_new)
            end_idx = min(int((i + 1) * segments_per_new), len(base_timed_segments))
            
            start_time = base_timed_segments[start_idx]['start']
            end_time = base_timed_segments[end_idx - 1]['end']
            
            aligned_segments.append({
                'start': start_time,
                'end': end_time,
                'text': new_text_seg
            })
    
    else:
        # More new segments - distribute timing proportionally
        print("Distributing timing proportionally")
        
        # Calculate character-based weights for better distribution
        char_counts = [len(seg) for seg in new_segments]
        total_chars = sum(char_counts)
        
        current_time = total_start_time
        
        for i, (new_text_seg, char_count) in enumerate(zip(new_segments, char_counts)):
            # Calculate duration based on character proportion
            if total_chars > 0:
                char_ratio = char_count / total_chars
                duration = total_duration * char_ratio
            else:
                duration = total_duration / len(new_segments)
            
            # Apply reasonable bounds
            min_duration = max(1.0, len(new_text_seg.split()) * 0.5)
            max_duration = min(5.0, len(new_text_seg) * 0.12)
            duration = max(min_duration, min(max_duration, duration))
            
            start_time = current_time
            end_time = min(start_time + duration, total_end_time)
            
            aligned_segments.append({
                'start': start_time,
                'end': end_time,
                'text': new_text_seg
            })
            
            current_time = end_time + 0.1  # Small gap
            
            # Don't exceed total time
            if current_time >= total_end_time:
                break
    
    print(f"Aligned to {len(aligned_segments)} final segments")
    return aligned_segments

def generate_all_srt_files_improved(upload_dir, video_path, wav_audio_path, results):
    """Generate all SRT files with improved video synchronization"""
    srt_files = {}
    
    try:
        print("=== Starting Enhanced SRT Generation with Video Sync ===")
        
        # Get video duration for reference
        video_duration = get_video_duration(video_path)
        print(f"Video duration: {video_duration} seconds")
        
        # Generate precise timed segments from the original Tamil audio
        print("Generating precise timed segments from Tamil audio...")
        base_timed_segments = generate_precise_timed_segments(wav_audio_path, video_path, language="ta")
        
        # If Whisper timing fails, use smart fallback
        if not base_timed_segments and results['tanglish_tamil']:
            print("Whisper timing failed, using smart fallback method...")
            base_timed_segments = create_smart_fallback_segments(
                wav_audio_path, 
                video_path,
                results['tanglish_tamil']
            )
        
        if not base_timed_segments:
            print("ERROR: No timing segments could be generated!")
            return {}
        
        print(f"Using {len(base_timed_segments)} base timing segments")
        print(f"Time range: {base_timed_segments[0]['start']:.2f}s to {base_timed_segments[-1]['end']:.2f}s")
        

        if results['tanglish_tamil']:
            print("\n--- Generating Tanglish Tamil SRT ---")
            # Re-align Tamil text to ensure consistency
            tanglish_tamil_aligned_segments = align_text_to_timing(
                base_timed_segments, 
                results['tanglish_tamil'], 
                "ta"
            )
            
            if tanglish_tamil_aligned_segments:
                tanglish_tamil_srt_content = create_srt_content(tanglish_tamil_aligned_segments)
                if tanglish_tamil_srt_content:
                    tanglish_tamil_srt_path = os.path.join(upload_dir, "tanglish_tamil_subtitles.srt")
                    with open(tanglish_tamil_srt_path, "w", encoding="utf-8") as f:
                        f.write(tanglish_tamil_srt_content)
                    srt_files['tanglish_tamil'] = tanglish_tamil_srt_path
                    print("✓ Generated Tanglish Tamil SRT file")
        
        # Generate SRT for English
        if results['english']:
            print("\n--- Generating English SRT ---")
            english_aligned_segments = align_text_to_timing(
                base_timed_segments, 
                results['english'], 
                "en"
            )
            
            if english_aligned_segments:
                english_srt_content = create_srt_content(english_aligned_segments)
                if english_srt_content:
                    english_srt_path = os.path.join(upload_dir, "english_subtitles.srt")
                    with open(english_srt_path, "w", encoding="utf-8") as f:
                        f.write(english_srt_content)
                    srt_files['english'] = english_srt_path
                    print("✓ Generated English SRT file")
        
        # Generate SRT for Tanglish
        if results['tanglish_english'] and results['tanglish_english'] != "Tanglish-english transcription failed":
            print("\n--- Generating Tanglish SRT ---")
            tanglish_english_aligned_segments = align_text_to_timing(
                base_timed_segments, 
                results['tanglish_english'], 
                "tanglish_english"
            )
            
            if tanglish_english_aligned_segments:
                tanglish_english_srt_content = create_srt_content(tanglish_english_aligned_segments)
                if tanglish_english_srt_content:
                    tanglish_english_srt_path = os.path.join(upload_dir, "tanglish_english_subtitles.srt")
                    with open(tanglish_english_srt_path, "w", encoding="utf-8") as f:
                        f.write(tanglish_english_srt_content)
                    srt_files['tanglish_english'] = tanglish_english_srt_path
                    print("✓ Generated Tanglish-English SRT file")
        
        # Generate SRT for Standard Tamil
        if results['tamil']:
            print("\n--- Generating Tamil SRT ---")
            tamil_aligned_segments = align_text_to_timing(
                base_timed_segments, 
                results['tamil'], 
                "ta"
            )
            
            if tamil_aligned_segments:
                tamil_srt_content = create_srt_content(tamil_aligned_segments)
                if tamil_srt_content:
                    tamil_srt_path = os.path.join(upload_dir, "tamil_subtitles.srt")
                    with open(tamil_srt_path, "w", encoding="utf-8") as f:
                        f.write(tamil_srt_content)
                    srt_files['tamil'] = tamil_srt_path
                    print("✓ Generated Tamil SRT file")
        
        print(f"\n=== Successfully generated {len(srt_files)} synchronized SRT files ===")
        
        # Validation: Check if timing makes sense
        for srt_type, srt_path in srt_files.items():
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Extract last timestamp to verify it doesn't exceed video duration
                timestamps = re.findall(r'(\d{2}:\d{2}:\d{2},\d{3})', content)
                if timestamps and video_duration:
                    last_timestamp = timestamps[-1]
                    # Convert to seconds for comparison
                    h, m, s_ms = last_timestamp.split(':')
                    s, ms = s_ms.split(',')
                    last_seconds = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
                    
                    if last_seconds > video_duration + 1:  # Allow 1 second tolerance
                        print(f"Warning: {srt_type} SRT extends beyond video duration ({last_seconds:.1f}s > {video_duration:.1f}s)")
        
        return srt_files
    
    except Exception as e:
        print(f"ERROR generating SRT files: {e}")
        import traceback
        traceback.print_exc()
        return {}