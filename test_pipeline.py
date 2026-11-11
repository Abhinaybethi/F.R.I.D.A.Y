#!/usr/bin/env python
"""Test pipeline end-to-end."""
from friday.core.assistant import Friday
from friday.utils.config_validator import validate_config
import yaml

# Load and validate config
with open('config.yaml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
valid, cfg, messages = validate_config(cfg)
print(f'Config valid: {valid}')
if messages:
    print(f'Messages: {messages}')

# Check security settings
tools = cfg.get('tools', {}) or {}
dry_run_val = tools.get('dry_run', True)
allow_real = tools.get('allow_real_execution', False)
print(f'dry_run: {bool(dry_run_val)}')
print(f'allow_real_execution: {bool(allow_real)}')

# Create Friday in text mode
assistant = Friday(config_path='config.yaml', text_mode=True)

# Test some commands via conversation_manager
print('\n--- Testing commands ---')

# Test time
response, _ = assistant.conversation_manager.handle_transcript('what time is it')
print(f'Time: {response}')

# Test open app (dry run)
response, _ = assistant.conversation_manager.handle_transcript('open chrome')
print(f'Open chrome: {response}')

# Test get time again
response, _ = assistant.conversation_manager.handle_transcript('what is the current time')
print(f'Current time: {response}')

# Test open app another
response, _ = assistant.conversation_manager.handle_transcript('open notepad')
print(f'Open notepad: {response}')

assistant.shutdown()
print('\nPipeline test complete!')