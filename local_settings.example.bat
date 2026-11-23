@echo off
rem Optional settings for THIS computer. Copy this file to local_settings.bat (that copy is kept out of Git),
rem remove "rem " in front of the lines you need and change the paths. start.bat and install.bat read it.
rem Only local folders go here. Nothing in this file sends anything off the computer.

rem 1. Use the AI packages (torch, transformers ...) already installed in another folder's .venv,
rem    so "install.bat model" does not have to download them again. Point at that folder's python.exe:
rem set "LRT_MODEL_PYTHON=C:\path\to\other\copy\.venv\Scripts\python.exe"

rem 2. Where the downloaded model files are. Only needed if they are NOT in the usual place
rem    (C:\Users\<you>\.cache\huggingface). Point at the folder that contains "hub":
rem set "HF_HOME=F:\hf-cache"

rem 3. Or point straight at a model folder (the one with config.json and the *.safetensors files):
rem set "CHAT_MODEL=F:\models\Qwen3.5-9B"
rem set "EMBED_MODEL=F:\models\bge-base-en-v1.5"

rem 4. Use Claude (Anthropic's API) instead of the local model. ONLY if your organisation has approved it:
rem    your messages and the draft on the form leave this computer. Use SYNTHETIC data for the course.
rem set "LRT_BASE_URL=https://api.anthropic.com/v1"
rem set "LRT_AI_MODEL=claude-sonnet-5-5"
rem set "LRT_ALLOW_REMOTE_AI=1"
rem    Let people pick the model in the chat (only these are accepted; Opus is slower and costs more):
rem set "LRT_AI_MODELS=claude-sonnet-5-5,claude-opus-5-5,claude-haiku-5-5"
rem    The key: do NOT write it in this file. Set it once for your Windows user, then open a new window:
rem      setx LRT_AI_KEY "your-claude-api-key"
rem    A key that is not scoped to a workspace also needs:  set "LRT_AI_WORKSPACE=your-workspace-id"
