import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import threading
from friday.voice.text_to_speech import TextToSpeech

def test_tts_pipeline():
    print("Initializing TTS...")
    tts = TextToSpeech(engine="piper")
    
    print("\n1. Testing Text Cleaning")
    assert tts._clean_for_speech("Normal text.") == "Normal text."
    print("Text cleaning OK.")
    
    print("\n2. Testing Short Speech")
    t0 = time.time()
    tts.speak("Hello.")
    t1 = time.time()
    print(f"Short speech completed in {t1-t0:.2f}s")
    
    print("\n3. Testing Interruptibility")
    tts.abort_event.clear()
    tts.stop()
    assert tts.abort_event.is_set() is True
    print("Interruption successful.")

    print("\nALL TTS TESTS PASSED")

if __name__ == "__main__":
    test_tts_pipeline()
