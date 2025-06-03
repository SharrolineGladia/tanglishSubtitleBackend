import os
import torch
import time
import speech_recognition as sr
from pydub import AudioSegment
from whisper_loader import get_model

from api.services.tanglish_service import contains_tamil_script, filter_non_tamil_words

from faster_whisper import WhisperModel
from googletrans import Translator


def transcribe_tamil_audio(audio_path, model=None):    
    recognizer = sr.Recognizer()

    with sr.AudioFile(audio_path) as source:
        recognizer.adjust_for_ambient_noise(source, duration=1.0)
        audio_data = recognizer.record(source)

    tamil_text = ""

    # Try Google Speech Recognition
    try:
        tamil_text = recognizer.recognize_google(audio_data, language="ta-IN")
    except Exception as e:
        print(f"Google Speech Recognition error: {str(e)}")

    # Use faster-whisper fallback if needed
    if not tamil_text or len(tamil_text.strip()) < 10:
        try:
            if model is None:
                model = WhisperModel("base", device="cpu", compute_type="int8")

            segments, _ = model.transcribe(audio_path, language="ta", beam_size=5)
            tamil_text = " ".join([seg.text for seg in segments])
        except Exception as e:
            print(f"Whisper transcription error: {str(e)}")

    return tamil_text


def transcribe_tamil_from_chunks(audio_chunks, model=None):
    all_tamil_text = ""

    for i, chunk_path in enumerate(audio_chunks):
        print(f"Processing Tamil chunk {i+1}/{len(audio_chunks)}...")
        chunk_text = transcribe_tamil_audio(chunk_path, model=model)

        filtered_text = filter_non_tamil_words(chunk_text)
        if len(filtered_text) < len(chunk_text) * 0.5:
            all_tamil_text += " " + chunk_text
        else:
            all_tamil_text += " " + filtered_text

    return all_tamil_text.strip()


def process_pure_tamil_from_audio(audio_chunks, model=None):
    pure_tamil_text = transcribe_tamil_from_chunks(audio_chunks, model=model)

    if not contains_tamil_script(pure_tamil_text):
        try:
            combined_audio = AudioSegment.empty()
            for chunk_path in audio_chunks:
                chunk = AudioSegment.from_file(chunk_path)
                combined_audio += chunk

            combined_path = os.path.join(os.path.dirname(audio_chunks[0]), "combined_for_tamil.wav")
            combined_audio.export(combined_path, format="wav")

            if model is None:
                model = WhisperModel("base", device="cpu", compute_type="int8")

            segments, _ = model.transcribe(combined_path, language="ta", beam_size=5)
            pure_tamil_text = " ".join([seg.text for seg in segments])

            if os.path.exists(combined_path):
                os.remove(combined_path)
        except Exception as e:
            print(f"Enhanced Whisper transcription failed: {e}")

    return pure_tamil_text


def transcribe_with_whisper(audio_path, language="ta", model=None):
    try:
        if not model:
            model = WhisperModel("large-v3", device="cpu", compute_type="int8")

        segments, _ = model.transcribe(audio_path, language=language, beam_size=5)
        text = " ".join([seg.text for seg in segments])

        if language == "ta" and not contains_tamil_script(text):
            # Retry once if no Tamil script detected
            segments, _ = model.transcribe(audio_path, language="ta", beam_size=5)
            text = " ".join([seg.text for seg in segments])

        if language == "ta":
            return filter_non_tamil_words(text)
        return text

    except Exception as e:
        print(f"Error with Whisper transcription: {e}")
        return ""
 
