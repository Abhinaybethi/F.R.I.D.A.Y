# Friday — Personal AI Voice Assistant

A desktop voice assistant (Windows/Mac) with a natural female voice, wake-word
activation ("Friday"), a knowledge brain grounded in live web search, and
agent-style control over apps and files on your computer.

## A quick, honest note on "training on the whole internet for free, unlimited"

That exact phrase isn't something any setup can deliver — training a model
from scratch on internet-scale data costs millions of dollars in compute.
What this project gives you *instead*, which achieves the same practical
goal for $0:

- **A local open-source LLM (via [Ollama](https://ollama.com))** as Friday's
  "brain." It runs entirely on your own computer — no API bill, no rate
  limit, no expiring free tier. This is the genuinely free-and-unlimited part.
- **Live, free web search** (no API key) so Friday's answers are grounded in
  current internet information instead of being frozen at a training cutoff.

Together, these behave like a knowledge base "trained on the internet,"
without you ever needing to actually train anything.

---

## What Friday can do out of the box

Say **"Friday"** to wake her up, then say a command:

| You say | What happens |
|---|---|
| "Open Chrome" / "Open Notepad" | Launches the app |
| "Close Spotify" | Terminates the app |
| "Open file budget.xlsx" | Opens a file (searches Desktop/Documents/Downloads if no exact path given) |
| "Find file invoice" | Searches your common folders for a matching file |
| "Create a folder called Taxes" | Creates a folder on your Desktop |
| "What time is it?" | Speaks the current time |
| "What's my battery?" | Speaks battery percentage and charging state |
| "Set volume to 50" | Sets system volume (Mac works out of the box; Windows needs an optional package, see below) |
| "Search the web for the Mumbai weather forecast" | Live web search, speaks a summary |
| "What is quantum entanglement?" / "Who is..." / "Explain..." | Answered by the local LLM, grounded with a quick web search |
| "Stop" / "Exit" / "Quit" / "Goodbye" | Shuts Friday down |

The command logic lives in one readable file — `friday/core/command_router.py`
— so adding new voice commands later is straightforward.

---

## Folder structure

```
friday-assistant/
├── main.py                      # entry point — run this
├── config.yaml                  # all settings (wake word, voice, model name...)
├── requirements.txt
├── data/
│   └── app_aliases.json         # spoken app names -> real app names per OS
├── logs/
│   └── friday.log               # created automatically when you run Friday
└── friday/
    ├── core/
    │   ├── assistant.py         # wires everything together, runs the main loop
    │   ├── wake_word.py         # listens for "Friday"
    │   └── command_router.py    # decides what a spoken command should do
    ├── voice/
    │   ├── speech_to_text.py    # microphone -> text
    │   └── text_to_speech.py    # text -> natural female voice
    ├── brain/
    │   ├── llm_client.py        # talks to your local Ollama model
    │   └── web_search.py        # free, unlimited web search
    ├── system_control/
    │   ├── app_control.py       # open/close applications
    │   ├── file_control.py      # open/find/create files & folders
    │   └── system_info.py       # battery, volume
    ├── skills/                  # turns each intent into a spoken response
    │   ├── knowledge_skill.py
    │   ├── app_skill.py
    │   ├── file_skill.py
    │   └── system_skill.py
    └── utils/
        └── logger.py
```

---

## Setup

### 1. Install Python 3.10+
Check with `python3 --version`. Get it from [python.org](https://python.org) if needed.

### 2. Create a virtual environment (recommended)

```bash
cd friday-assistant
python3 -m venv .venv

# Windows:
.venv\Scripts\activate
# Mac:
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

**`pyaudio` is the most common install snag** — it needs a system audio
library underneath it:

- **Mac:** `brew install portaudio` first, then `pip install pyaudio`
- **Windows:** if `pip install pyaudio` fails, run:
  ```
  pip install pipwin
  pipwin install pyaudio
  ```

### 4. Install Ollama (the free, unlimited knowledge brain)

1. Download and install from **https://ollama.com** (Windows and Mac supported).
2. Pull a model (one-time download, then it's yours forever, offline, free):
   ```bash
   ollama pull llama3.2
   ```
   `llama3.2` (~2GB) is a good default. If your computer is older/slower, try
   the smaller `phi3` instead and update `ollama_model` in `config.yaml` to
   match.
3. Leave Ollama running in the background (it usually starts automatically
   after install, and runs as a small background service).

> If you skip this step, Friday still works — she'll just answer knowledge
> questions using web search summaries only, instead of a fully reasoned LLM
> answer.

### 5. Grant microphone permission

- **Mac:** System Settings → Privacy & Security → Microphone → allow your
  Terminal app (or whichever app you run Python from).
- **Windows:** Settings → Privacy & Security → Microphone → make sure
  desktop apps are allowed to access it.

### 6. (Optional) Enable voice-controlled volume on Windows

Uncomment the last two lines in `requirements.txt` (`pycaw`, `comtypes`) and
re-run `pip install -r requirements.txt`. Mac volume control works
out of the box with no extra install.

### 7. Customize your apps

Open `data/app_aliases.json` and add the apps you actually use, with the
exact name your OS expects. If "open spotify" doesn't work, replace the
value with the full path to the app/exe.

### 8. Run Friday

```bash
python main.py
```

You should hear: *"Friday online. Say my name whenever you need me."*
Then say **"Friday"**, wait for "Yes?", and speak your command.

---

## Configuration (`config.yaml`)

| Setting | What it does |
|---|---|
| `wake_word` | The word Friday listens for (default `"friday"`) |
| `voice.engine` | `"edge"` for a natural female voice (needs internet) or `"pyttsx3"` for fully offline |
| `voice.edge_voice` | Try `en-US-JennyNeural`, `en-GB-SoniaNeural`, or `en-AU-NatashaNeural` for different female voices |
| `brain.ollama_model` | Which local model Ollama should use |

---

## Going fully offline (optional, advanced)

Two pieces currently use the internet for convenience:
- **Speech-to-text** uses Google's free recognition endpoint.
- **Edge voice** (`voice.engine: "edge"`) needs internet to generate speech.

If you want Friday to work with **zero internet dependency**:
- Set `voice.engine: "pyttsx3"` in `config.yaml` (uses your OS's built-in
  voice — more robotic, but 100% offline).
- Swap `speech_recognition`'s Google recognizer for an offline engine like
  [Vosk](https://alphacephei.com/vosk/) in `friday/voice/speech_to_text.py`.
- Ollama (the brain) is already fully offline once the model is downloaded.

---

## Extending Friday

To add a new voice command:
1. Write a handler function in the relevant file under `friday/skills/`
   (or create a new skill file).
2. Add a matching `elif`/regex branch in
   `friday/core/command_router.py`.

That's it — no need to touch the voice, brain, or system_control layers
unless the new command needs a genuinely new capability.

---

## Troubleshooting..

- **"No module named pyaudio"** → see the pyaudio install notes above.
- **Friday doesn't hear anything** → check OS microphone permissions, and
  that the correct mic is set as your system default input.
- **No sound comes out** → check `voice.engine` in `config.yaml`; if `"edge"`
  fails silently due to no internet, it should auto-fallback to `"pyttsx3"`,
  but you can set it directly to test.
- **Knowledge answers feel shallow** → make sure `ollama` is actually
  running (`ollama list` in a terminal should show your pulled model).
- **An app won't open/close** → edit `data/app_aliases.json` with the exact
  app name or full path for your OS.
