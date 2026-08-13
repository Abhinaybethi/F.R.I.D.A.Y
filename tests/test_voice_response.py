import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import yaml
from friday.core.conversation import ConversationManager
from friday.voice.text_to_speech import TextToSpeech

class MockTTS(TextToSpeech):
    def __init__(self):
        super().__init__(engine="piper")
        self.spoken = []

    def speak(self, text: str) -> None:
        clean_text = self._clean_for_speech(text)
        print(f"MockTTS heard: {text} -> Spoke: {clean_text}")
        self.spoken.append(clean_text)

def test_voice_response():
    print("Initializing ConversationManager and MockTTS...")
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    tts = MockTTS()

    def handle(transcript):
        response, keep_running = cm.handle_transcript(transcript)
        if response:
            tts.speak(response)
        return keep_running

    print("\n[Test 1] 'what time is it'")
    handle("what time is it")
    assert any("It's" in s for s in tts.spoken[-1:]), "TTS should speak the time."

    print("\n[Test 2] 'open chrome'")
    handle("open chrome")
    assert tts.spoken[-1] == "Opening Chrome.", f"Unexpected TTS output: {tts.spoken[-1]}"

    print("\n[Test 3] 'open groom' (confirmation)")
    handle("open groom")
    assert tts.spoken[-1] == "Did you mean Chrome?", f"Unexpected TTS output: {tts.spoken[-1]}"

    print("\n[Test 4] 'yes' (execution)")
    handle("yes")
    assert tts.spoken[-1] == "Opening Chrome.", f"Unexpected TTS output: {tts.spoken[-1]}"

    print("\n[Test 5] 'open groom' again for cancel test")
    handle("open groom")
    
    print("\n[Test 6] 'cancel' (cancellation)")
    handle("cancel")
    assert tts.spoken[-1] == "Cancelled.", f"Unexpected TTS output: {tts.spoken[-1]}"
    
    print("\n[Test 7] 'stop' (shutdown)")
    keep_running = handle("stop")
    assert keep_running is False
    assert tts.spoken[-1] == "Goodbye.", f"Unexpected TTS output: {tts.spoken[-1]}"

    print("\nALL VOICE RESPONSE TESTS PASSED")

if __name__ == "__main__":
    test_voice_response()
