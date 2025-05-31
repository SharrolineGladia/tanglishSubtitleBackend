import re

def contains_tamil_script(text):
    """
    Check if text contains Tamil characters
    
    Args:
        text (str): Text to check
    
    Returns:
        bool: True if text contains Tamil script, False otherwise
    """
    return any('\u0B80' <= c <= '\u0BFF' for c in text)

def filter_non_tamil_words(text):
    """
    Filter out English words from Tamil text
    
    Args:
        text (str): Mixed text
    
    Returns:
        str: Text containing only Tamil words
    """
    if not text:
        return ""
    
    # Split text into words
    words = text.split()
    filtered_words = []
    
    for word in words:
        # Check if the word has Tamil script
        if contains_tamil_script(word):
            filtered_words.append(word)
        # For words with mixed scripts, keep only Tamil parts
        elif any('\u0B80' <= c <= '\u0BFF' for c in word):
            tamil_chars = ''.join(c for c in word if '\u0B80' <= c <= '\u0BFF')
            if tamil_chars:
                filtered_words.append(tamil_chars)
    
    return ' '.join(filtered_words)

def contains_english_words(text):
    """
    Check for English words in Tamil text
    
    Args:
        text (str): Text to check
    
    Returns:
        bool: True if text contains English words, False otherwise
    """
    # Simple regex to detect English words (3+ consecutive ASCII letters)
    english_pattern = re.compile(r'[a-zA-Z]{3,}')
    return bool(english_pattern.search(text))

def tamil_to_tanglish(text):
    """
    Tamil to Tanglish (Romanized) conversion
    
    Args:
        text (str): Tamil text
    
    Returns:
        str: Romanized Tanglish text
    """
    # Define mappings for Tamil characters to romanized equivalents

    # Tamil vowels (uyir)
    vowels = {
        'அ': 'a', 'ஆ': 'aa', 'இ': 'i', 'ஈ': 'ee',
        'உ': 'u', 'ஊ': 'oo', 'எ': 'e', 'ஏ': 'ae',
        'ஐ': 'ai', 'ஒ': 'o', 'ஓ': 'oa', 'ஔ': 'au'
    }

    # Tamil consonants (mei)
    consonants = {
        'க்': 'k', 'ங்': 'ng', 'ச்': 'ch', 'ஞ்': 'nj',
        'ட்': 't', 'ண்': 'n', 'த்': 'th', 'ந்': 'n',
        'ப்': 'p', 'ம்': 'm', 'ய்': 'y', 'ர்': 'r',
        'ல்': 'l', 'வ்': 'v', 'ழ்': 'zh', 'ள்': 'l',
        'ற்': 'tr', 'ன்': 'n', 'ஜ்': 'j', 'ஷ்': 'sh',
        'ஸ்': 's', 'ஹ்': 'h'
    }

    # Tamil uyirmei (compound characters) - comprehensive list
    uyirmei = {
        # க family (ka)
        'க': 'ka', 'கா': 'kaa', 'கி': 'ki', 'கீ': 'kee',
        'கு': 'ku', 'கூ': 'koo', 'கெ': 'ke', 'கே': 'kae',
        'கை': 'kai', 'கொ': 'ko', 'கோ': 'koa', 'கௌ': 'kau',

        # ங family (nga)
        'ங': 'nga', 'ஙா': 'ngaa', 'ஙி': 'ngi', 'ஙீ': 'ngee',
        'ஙு': 'ngu', 'ஙூ': 'ngoo', 'ஙெ': 'nge', 'ஙே': 'ngae',
        'ஙை': 'ngai', 'ஙொ': 'ngo', 'ஙோ': 'ngoa', 'ஙௌ': 'ngau',

        # ச family (cha)
        'ச': 'cha', 'சா': 'chaa', 'சி': 'chi', 'சீ': 'chee',
        'சு': 'chu', 'சூ': 'choo', 'செ': 'che', 'சே': 'chae',
        'சை': 'chai', 'சொ': 'cho', 'சோ': 'choa', 'சௌ': 'chau',

        # ஞ family (nja)
        'ஞ': 'nja', 'ஞா': 'njaa', 'ஞி': 'nji', 'ஞீ': 'njee',
        'ஞு': 'nju', 'ஞூ': 'njoo', 'ஞெ': 'nje', 'ஞே': 'njae',
        'ஞை': 'njai', 'ஞொ': 'njo', 'ஞோ': 'njoa', 'ஞௌ': 'njau',

        # ட family (ta/da)
        'ட': 'ta', 'டா': 'taa', 'டி': 'ti', 'டீ': 'tee',
        'டு': 'tu', 'டூ': 'too', 'டெ': 'te', 'டே': 'tae',
        'டை': 'tai', 'டொ': 'to', 'டோ': 'toa', 'டௌ': 'tau',

        # ண family (na)
        'ண': 'na', 'ணா': 'naa', 'ணி': 'ni', 'ணீ': 'nee',
        'ணு': 'nu', 'ணூ': 'noo', 'ணெ': 'ne', 'ணே': 'nae',
        'ணை': 'nai', 'ணொ': 'no', 'ணோ': 'noa', 'ணௌ': 'nau',

        # த family (tha)
        'த': 'tha', 'தா': 'thaa', 'தி': 'thi', 'தீ': 'thee',
        'து': 'thu', 'தூ': 'thoo', 'தெ': 'the', 'தே': 'thae',
        'தை': 'thai', 'தொ': 'tho', 'தோ': 'thoa', 'தௌ': 'thau',

        # ந family (na)
        'ந': 'na', 'நா': 'naa', 'நி': 'ni', 'நீ': 'nee',
        'நு': 'nu', 'நூ': 'noo', 'நெ': 'ne', 'நே': 'nae',
        'நை': 'nai', 'நொ': 'no', 'நோ': 'noa', 'நௌ': 'nau',

        # ப family (pa/ba)
        'ப': 'pa', 'பா': 'paa', 'பி': 'pi', 'பீ': 'pee',
        'பு': 'pu', 'பூ': 'poo', 'பெ': 'pe', 'பே': 'pae',
        'பை': 'pai', 'பொ': 'po', 'போ': 'poa', 'பௌ': 'pau',

        # ம family (ma)
        'ம': 'ma', 'மா': 'maa', 'மி': 'mi', 'மீ': 'mee',
        'மு': 'mu', 'மூ': 'moo', 'மெ': 'me', 'மே': 'mae',
        'மை': 'mai', 'மொ': 'mo', 'மோ': 'moa', 'மௌ': 'mau',

        # ய family (ya)
        'ய': 'ya', 'யா': 'yaa', 'யி': 'yi', 'யீ': 'yee',
        'யு': 'yu', 'யூ': 'yoo', 'யெ': 'ye', 'யே': 'yae',
        'யை': 'yai', 'யொ': 'yo', 'யோ': 'yoa', 'யௌ': 'yau',

        # ர family (ra)
        'ர': 'ra', 'ரா': 'raa', 'ரி': 'ri', 'ரீ': 'ree',
        'ரு': 'ru', 'ரூ': 'roo', 'ரெ': 're', 
        # ர family (ra) (continued)
        'ரே': 'rae',
        'ரை': 'rai', 'ரொ': 'ro', 'ரோ': 'roa', 'ரௌ': 'rau',

        # ல family (la)
        'ல': 'la', 'லா': 'laa', 'லி': 'li', 'லீ': 'lee',
        'லு': 'lu', 'லூ': 'loo', 'லெ': 'le', 'லே': 'lae',
        'லை': 'lai', 'லொ': 'lo', 'லோ': 'loa', 'லௌ': 'lau',

        # வ family (va)
        'வ': 'va', 'வா': 'vaa', 'வி': 'vi', 'வீ': 'vee',
        'வு': 'vu', 'வூ': 'voo', 'வெ': 've', 'வே': 'vae',
        'வை': 'vai', 'வொ': 'vo', 'வோ': 'voa', 'வௌ': 'vau',

        # ழ family (zha)
        'ழ': 'zha', 'ழா': 'zhaa', 'ழி': 'zhi', 'ழீ': 'zhee',
        'ழு': 'zhu', 'ழூ': 'zhoo', 'ழெ': 'zhe', 'ழே': 'zhae',
        'ழை': 'zhai', 'ழொ': 'zho', 'ழோ': 'zhoa', 'ழௌ': 'zhau',

        # ள family (la)
        'ள': 'la', 'ளா': 'laa', 'ளி': 'li', 'ளீ': 'lee',
        'ளு': 'lu', 'ளூ': 'loo', 'ளெ': 'le', 'ளே': 'lae',
        'ளை': 'lai', 'ளொ': 'lo', 'ளோ': 'loa', 'ளௌ': 'lau',

        # ற family (tra)
        'ற': 'tra', 'றா': 'traa', 'றி': 'tri', 'றீ': 'tree',
        'று': 'tru', 'றூ': 'troo', 'றெ': 'tre', 'றே': 'trae',
        'றை': 'trai', 'றொ': 'tro', 'றோ': 'troa', 'றௌ': 'trau',

        # ன family (na)
        'ன': 'na', 'னா': 'naa', 'னி': 'ni', 'னீ': 'nee',
        'னு': 'nu', 'னூ': 'noo', 'னெ': 'ne', 'னே': 'nae',
        'னை': 'nai', 'னொ': 'no', 'னோ': 'noa', 'னௌ': 'nau',

        # ஜ family (ja)
        'ஜ': 'ja', 'ஜா': 'jaa', 'ஜி': 'ji', 'ஜீ': 'jee',
        'ஜு': 'ju', 'ஜூ': 'joo', 'ஜெ': 'je', 'ஜே': 'jae',
        'ஜை': 'jai', 'ஜொ': 'jo', 'ஜோ': 'joa', 'ஜௌ': 'jau',

        # ஷ family (sha)
        'ஷ': 'sha', 'ஷா': 'shaa', 'ஷி': 'shi', 'ஷீ': 'shee',
        'ஷு': 'shu', 'ஷூ': 'shoo', 'ஷெ': 'she', 'ஷே': 'shae',
        'ஷை': 'shai', 'ஷொ': 'sho', 'ஷோ': 'shoa', 'ஷௌ': 'shau',

        # ஸ family (sa)
        'ஸ': 'sa', 'ஸா': 'saa', 'ஸி': 'si', 'ஸீ': 'see',
        'ஸு': 'su', 'ஸூ': 'soo', 'ஸெ': 'se', 'ஸே': 'sae',
        'ஸை': 'sai', 'ஸொ': 'so', 'ஸோ': 'soa', 'ஸௌ': 'sau',

        # ஹ family (ha)
        'ஹ': 'ha', 'ஹா': 'haa', 'ஹி': 'hi', 'ஹீ': 'hee',
        'ஹு': 'hu', 'ஹூ': 'hoo', 'ஹெ': 'he', 'ஹே': 'hae',
        'ஹை': 'hai', 'ஹொ': 'ho', 'ஹோ': 'hoa', 'ஹௌ': 'hau',

        # Special characters and combinations
        'ஃ': 'ak', 'ஸ்ரீ': 'sri',

        # Special additions for common usage
        'டா': 'da', 'டி': 'di', 'டு': 'du',  # These can sound like 'da' in spoken Tamil
        'க்ஷ': 'ksha', 'ஶ்ரீ': 'shri'
    }

    # Grantha consonants (additional Tamil letters)
    grantha = {
        'ஶ': 'sha', 'ஜ': 'ja', 'ஷ': 'sha', 'ஸ': 'sa', 'ஹ': 'ha'
    }

    # Common Tamil word suffixes and context-specific conversions
    suffixes = {
        'இல்': 'il', 'இன்': 'in', 'ஆல்': 'aal',
        'உடன்': 'udan', 'க்கு': 'kku', 'த்தில்': 'thil',
        'ல்': 'l', 'ன்': 'n', 'ம்': 'm'
    }

    # Convert Tamil text to Tanglish
    result = ""
    i = 0

    while i < len(text):
        # Try to match the longest character combinations first
        found = False
        for length in range(min(4, len(text) - i), 0, -1):
            substring = text[i:i+length]

            # Check if the substring exists in our mappings
            if substring in uyirmei:
                result += uyirmei[substring]
                i += length
                found = True
                break
            elif substring in vowels:
                result += vowels[substring]
                i += length
                found = True
                break
            elif substring in consonants:
                result += consonants[substring]
                i += length
                found = True
                break
            elif substring in suffixes:
                result += suffixes[substring]
                i += length
                found = True
                break
            elif substring in grantha:
                result += grantha[substring]
                i += length
                found = True
                break

        # If no match found, keep the character as is
        if not found:
            # Add a space between words
            if text[i] == ' ':
                result += ' '
            # Special case for Tamil pulli (virama)
            elif text[i] == '்':
                # Do nothing, it's handled by the consonant mappings
                pass
            # For English or other characters, just add them as is
            elif ord(text[i]) < 0x0B80 or ord(text[i]) > 0x0BFF:
                result += text[i]
            # If we missed any Tamil character, add a placeholder
            else:
                result += '?'
            i += 1

    # Post-processing to clean up the text
    # Fix double spaces and other formatting issues
    result = re.sub(r'\s+', ' ', result).strip()

    # Handle common spoken forms for better readability
    # Convert some patterns to match colloquial Tanglish
    result = result.replace('tha ', 'dha ').replace('thu ', 'dhu ')
    result = result.replace('ka ', 'ga ').replace('pa ', 'ba ')

    # Handle common suffixes 'da' and 'ah' for emphasis
    for word in ['da', 'ah', 'va', 'nga']:
        pattern = r'([a-z]+)' + word + r'\b'
        replacement = r'\1 ' + word
        result = re.sub(pattern, replacement, result)

    return result