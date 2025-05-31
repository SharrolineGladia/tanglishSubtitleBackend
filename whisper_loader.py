import os
import time
import threading
from faster_whisper import WhisperModel
import torch

# Set HuggingFace cache directory
MODELS_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cached_models")
os.makedirs(MODELS_CACHE_DIR, exist_ok=True)
os.environ["HUGGINGFACE_HUB_CACHE"] = MODELS_CACHE_DIR  #  Sets cache path properly

# Dictionary to hold loaded models
whisper_models = {}
model_lock = threading.Lock()

def load_model(model_size):
    """Thread-safe model loader for faster-whisper."""
    with model_lock:
        if model_size in whisper_models:
            print(f"Model '{model_size}' is already loaded.")
            return whisper_models[model_size]

        print(f"Loading faster-whisper model '{model_size}'...")
        start = time.time()

        model = WhisperModel(
            model_size,
            device="cuda" if torch.cuda.is_available() else "cpu",
            compute_type="float16" if torch.cuda.is_available() else "int8"
        )

        whisper_models[model_size] = model
        print(f"Model '{model_size}' loaded in {time.time() - start:.2f}s.")
        return model

def initialize_models(model_sizes=None):
    """Preload models in background threads."""
    if model_sizes is None:
        model_sizes = ["large-v3"]

    def preload(size):
        try:
            load_model(size)
            print(f"Preloaded model: {size}")
        except Exception as e:
            print(f"Failed to preload model '{size}': {e}")

    if not whisper_models:
        print("Preloading faster-whisper models in background...")
        threads = []
        for size in model_sizes:
            t = threading.Thread(target=preload, args=(size,))
            t.daemon = True
            t.start()
            threads.append(t)
    else:
        print("Models already preloaded.")

def get_model(model_size="large-v3"):
    """Retrieve a model, loading on demand if necessary."""
    return whisper_models.get(model_size) or load_model(model_size)
