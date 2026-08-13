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
    assert tts._clean_for_speech("[DRY RUN] Would open Chrome.") == "Opening Chrome."
    assert tts._clean_for_speech("[DRY RUN] Would close Chrome.") == "Closing Chrome."
    assert tts._clean_for_speech("[DRY RUN] Would search: https://www.google.com/search?q=python+tutorials") == "Searching for python tutorials."
    assert tts._clean_for_speech("[DRY RUN] Would open folder: C:\\Users\\abhin\\Downloads") == "Opening folder C:\\Users\\abhin\\Downloads"
    print("Text cleaning OK.")
    
    print("\n2. Testing Short Speech")
    t0 = time.time()
    tts.speak("Hello.")
    t1 = time.time()
    print(f"Short speech completed in {t1-t0:.2f}s")
    
    print("\n3. Testing Interruptibility")
    def stopper():
        time.sleep(0.5)
        print(" -> Requesting stop...")
        tts.stop()
        
    threading.Thread(target=stopper).start()
    
    t0 = time.time()
    # Speak a long string that takes > 2 seconds
    tts.speak("This is a significantly long sentence designed specifically to test if the text to speech engine can be safely and reliably interrupted while it is actively playing back audio to the user.")
    duration = time.time() - t0
    
    print(f"Speak method returned in {duration:.2f}s")
    if duration < 3.0:
        print("Interruption successful.")
    else:
        print("Interruption failed: played for too long.")
        assert False, "TTS did not interrupt."

    print("\nALL TTS TESTS PASSED")

if __name__ == "__main__":
    test_tts_pipeline()
