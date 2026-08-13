$tests = @(
    "tests/test_system_intents.py",
    "tests/test_confirmation.py",
    "tests/test_conversation_state.py",
    "tests/test_command_understanding.py",
    "tests/test_intent_router.py",
    "tests/test_tools.py",
    "tests/test_pipeline.py",
    "tests/test_real_tools.py",
    "tests/test_tts.py",
    "tests/test_voice_response.py",
    "tests/test_voice_conversation.py"
)

foreach ($test in $tests) {
    Write-Host "Running $test..."
    python $test
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Test failed: $test" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}
Write-Host "All tests passed!" -ForegroundColor Green
