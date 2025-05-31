import os
import moviepy.editor as mp
from pydub import AudioSegment

def extract_audio_from_video(video_path, audio_path):
    """
    Extract audio from video file
    
    Args:
        video_path (str): Path to the video file
        audio_path (str): Path to save the extracted audio
    
    Returns:
        str: Path to the extracted audio file
    """
    video = mp.VideoFileClip(video_path)
    audio = video.audio
    audio.write_audiofile(audio_path)
    video.close()  # Close video file to release resources
    return audio_path

def convert_audio_format(input_audio_path, output_audio_path):
    """
    Convert audio to WAV format for speech recognition
    
    Args:
        input_audio_path (str): Path to the input audio file
        output_audio_path (str): Path to save the converted audio
    
    Returns:
        str: Path to the converted audio file
    """
    audio = AudioSegment.from_file(input_audio_path)
    audio = audio.set_channels(1)  # Convert to mono
    audio = audio.set_frame_rate(16000)  # Set sample rate to 16kHz
    audio.export(output_audio_path, format="wav")
    return output_audio_path

def split_audio(audio_path, chunk_length_ms=20000, output_dir=None):
    """
    Split audio into chunks to handle longer videos
    
    Args:
        audio_path (str): Path to the audio file
        chunk_length_ms (int): Length of each chunk in milliseconds
        output_dir (str): Directory to save the chunks
    
    Returns:
        list: List of paths to the audio chunks
    """
    audio = AudioSegment.from_file(audio_path)
    chunks = []
    
    # Get the directory to save chunks
    if output_dir is None:
        output_dir = os.path.dirname(audio_path)
    
    # Split audio into chunks
    for i in range(0, len(audio), chunk_length_ms):
        chunk = audio[i:i + chunk_length_ms]
        chunk_path = os.path.join(output_dir, f"chunk_{i//chunk_length_ms}.wav")
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    
    return chunks