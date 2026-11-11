#!/usr/bin/env python
"""Extended pipeline test."""
from friday.core.assistant import Friday
import yaml

assistant = Friday(config_path='config.yaml', text_mode=True)

print('=== Extended Pipeline Tests ===\n')

# Test 1: Search web
print('Test 1: Search web')
response, _ = assistant.conversation_manager.handle_transcript('search for python tutorials')
print(f'  Result: {response}\n')

# Test 2: Open website
print('Test 2: Open website')
response, _ = assistant.conversation_manager.handle_transcript('go to google')
print(f'  Result: {response}\n')

# Test 3: Get battery (if available)
print('Test 3: Battery status')
response, _ = assistant.conversation_manager.handle_transcript('battery status')
print(f'  Result: {response}\n')

# Test 4: Volume control
print('Test 4: Set volume')
response, _ = assistant.conversation_manager.handle_transcript('set volume to 50')
print(f'  Result: {response}\n')

# Test 5: Remember something
print('Test 5: Remember')
response, _ = assistant.conversation_manager.handle_transcript('remember my favorite color is blue')
print(f'  Result: {response}\n')

# Test 6: Recall
print('Test 6: Recall')
response, _ = assistant.conversation_manager.handle_transcript('recall my favorite color')
print(f'  Result: {response}\n')

# Test 7: Conversational acknowledgment
print('Test 7: Thank you')
response, _ = assistant.conversation_manager.handle_transcript('thank you')
print(f'  Result: {response}\n')

# Test 8: System stop
print('Test 8: Stop')
response, should_continue = assistant.conversation_manager.handle_transcript('stop')
print(f'  Result: {response}, continue: {should_continue}\n')

assistant.shutdown()
print('=== All tests complete! ===')