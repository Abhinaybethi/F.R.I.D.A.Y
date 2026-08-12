import time
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from friday.voice.text_to_speech import TextToSpeech

def main():
    print("Initializing Local TTS (Kokoro + Piper fallback)...")
    t0 = time.time()
    tts = TextToSpeech(engine="kokoro", fallback_engine="piper", voice="af_heart")
    print(f"Initialization took {time.time() - t0:.2f}s")
    
    text = "Hello. I am Friday. My local voice system is working."
    print(f"\nSpeaking: '{text}'")
    
    t0 = time.time()
    tts.speak(text)
    
    print(f"\nTTS Engine: {tts.engine_name}")
    print(f"Generation time: {time.time() - t0:.2f} seconds")
    print("Playback: OK")

if __name__ == "__main__":
    main()
