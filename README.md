# I, Mechanic

I, Mechanic is a Windows desktop assistant for Assetto Corsa Competizione (ACC) telemetry. It reads MoTeC `.ld` logs, summarizes setup-relevant signals, and can turn the summary and driver feedback into structured setup suggestions. Projects, session history, and chat are stored locally.

This is an independent community project. It is not affiliated with or endorsed by Kunos Simulazioni or MoTeC.

## Features

- Parse ACC MoTeC `.ld` logs and summarize tyre temperatures and pressures, brake temperatures, driver inputs, electronics, wheel slip, suspension travel, and data quality.
- Keep projects, sessions, analysis results, and conversation history in a local SQLite database.
- Use LM Studio, Ollama, OpenAI, OpenRouter, Groq, or Together from the Qt interface.
- Analyze telemetry without an AI request by disabling AI analysis.

## Requirements

- Windows 10 or later.
- Python 3.9 through 3.13 is the supported source-install range for the current PySide6 pin. Python 3.8 and Python 3.14 or later are not currently supported.
- Install dependencies from `requirements.txt`. NumPy is used by telemetry parsing; PySide6 provides the default Qt interface. Pandas and Matplotlib support standalone features in the bundled `ldparser` parser.

Python 3.13 was used for the current test run. Other versions in the intended range should be tested in a clean environment before relying on them.

## Install and Run

From PowerShell in the repository directory:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m i_mechanic
```

## AI Providers and Data

The Qt interface offers LM Studio, Ollama, OpenAI, OpenRouter, Groq, and Together. For local use, start the selected model service. Hosted providers require credentials in environment variables; do not put API keys in source files or commit them:

| Provider | API key environment variable |
| --- | --- |
| LM Studio | `LMSTUDIO_API_KEY` (optional) |
| Ollama | `OLLAMA_API_KEY` (optional) |
| OpenAI | `OPENAI_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Groq | `GROQ_API_KEY` |
| Together | `TOGETHER_API_KEY` |

Each provider's model and server URL can be changed in the interface. Defaults can also be set with the corresponding `*_BASE_URL` and `*_MODEL` environment variables. The local defaults are `http://localhost:1234/v1` for LM Studio and `http://localhost:11434` for Ollama.

Telemetry parsing is local. When AI is enabled, the app sends the generated telemetry summary, driver feedback, and bounded project context to the selected provider. It does not send the original `.ld` file. Review the provider's privacy and retention terms before using a hosted service. Disable AI analysis to keep a session's analysis local.

The SQLite database is stored under `%LOCALAPPDATA%\I Mechanic\i_mechanic.sqlite3` (or the equivalent `AppData\Local` path when `LOCALAPPDATA` is not set). This brand-scoped location starts a fresh history; any database in the previous `AI Race Engineer` directory is left untouched and is not migrated. Qt preferences use the `I, Mechanic` settings namespace.

## Tests

Run the existing test suite with:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## Windows Installer Build

The planned Windows release uses a PyInstaller onedir bundle wrapped by Inno Setup. The installer build is separate from source installation and does not require users to install Python.

Install the build tool into the active development environment:

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm i-mechanic.spec
```

Then compile `installer\I-Mechanic.iss` with Inno Setup. The installer script expects the PyInstaller output at `dist\I Mechanic`. The release process must publish the corresponding source, `LICENSE`, and third-party notices alongside every installer artifact.

## Parser License and Project License

The bundled `ldparser` source is from [`gotzl/ldparser`](https://github.com/gotzl/ldparser), compared against upstream commit [`57935b7d7b15cce2532a593afba66728dc0927fe`](https://github.com/gotzl/ldparser/commit/57935b7d7b15cce2532a593afba66728dc0927fe). Its source matches that revision after normalizing line endings and the final newline. The parser is licensed under GPL-3.0; its complete license is retained at [`ldparser/LICENSE`](ldparser/LICENSE), with provenance details in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

The combined application is released under GPL-3.0-compatible terms. See [`LICENSE`](LICENSE) for the project notice, [`ldparser/LICENSE`](ldparser/LICENSE) for the complete GPL-3.0 text, and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for parser provenance. Do not apply a conflicting license to the combined project.
