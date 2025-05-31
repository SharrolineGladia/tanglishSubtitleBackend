import time
from googletrans import Translator

def translate_text(text, source_lang, target_lang):
    """
    Translate text using Google Translate
    
    Args:
        text (str): Text to translate
        source_lang (str): Source language code
        target_lang (str): Target language code
    
    Returns:
        str: Translated text
    """
    if not text:
        return ""

    translator = Translator()

    # Add a small delay to avoid rate limiting
    time.sleep(1)

    try:
        # For 'auto' language detection, use None instead
        src = None if source_lang == "auto" else source_lang
        translation = translator.translate(text, src=src, dest=target_lang)
        return translation.text
    except Exception as e:
        print(f"Translation error: {str(e)}")
        # Try one more time with a delay
        time.sleep(2)
        try:
            # Use None explicitly for auto-detection
            src = None if source_lang == "auto" else source_lang
            translation = translator.translate(text, src=src, dest=target_lang)
            return translation.text
        except Exception as e:
            print(f"Translation failed again: {str(e)}")
            return f"Translation failed: {text[:100]}..."