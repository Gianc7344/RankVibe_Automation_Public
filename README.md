# 🎬 RankVibe Automation — Autonomous AI Short-Form Video Generator 🚀

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Backend-007800?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org)
[![AI Integration](https://img.shields.io/badge/AI-OpenRouter-8E75C2?style=for-the-badge)](https://openrouter.ai)

**RankVibe Automation** is a highly advanced, autonomous Python tool designed to scout YouTube compilation videos, conceptualize dynamic "Top 5" or "Ranking" short-form video ideas using AI, split them into high-action scene clips via computer vision, and automatically stitch & render highly engaging short videos (Shorts, TikToks, Reels) using FFmpeg.

Features a clean, desktop-friendly launcher web interface and a robust end-to-end automation cycle.

---

## ✨ Key Features & Architecture

### 🧠 1. AI Concept Generation (OpenRouter AI)
*   **Intelligent Idea Generation:** Analyzes your channel rules and your last video's metrics to brainstorm brand-new, highly viral concepts using state-of-the-art LLMs via OpenRouter.
*   **Automatic Query Formulation:** Instantly formulates optimized YouTube search queries to discover the best compilation raw videos matching the concept.

### 🔍 2. Computer Vision Scene Splitting
*   **Action Scene Detection:** Surgically scans downloaded raw compilations and automatically detects scene transitions and high-intensity action frames using threshold-based frame contrast shifts.
*   **Instant Segment Previews:** Cuts and populates action clips within seconds, saving creators hours of manual clipping in Premier or CapCut.

### 🎚️ 3. Reverse Top 5 Video Stitcher
*   **Custom Dynamic Timeline:** Features a web interface where creators select 5 clips to compile them chronologically from #5 to #1.
*   **High-Speed Rendering:** Uses optimized FFmpeg pipelines to stitch transitions, scale resolutions, overlay audio, and render full-scale MP4 short videos in seconds.

### 🛠️ 4. Pro Diagnostic & Stress Testing Suite
*   **Diagnostic Tools (`diagnose.py`):** Automatically checks local system paths, validates OpenRouter key connections, and verifies the FFmpeg path.
*   **End-to-End Test Engine (`e2e_system_test.py`):** Simulates the entire generation cycle under sandboxed metrics to ensure robust server/local stability before batch rendering.

---

## 🏗️ Folder Structure & Decoupling

*   📁 **`templates/` & `index.html`**: The highly reactive web control dashboard.
*   📁 **`clips/` & `downloads/`**: Local cache directories storing downloaded segments and parsed action clips (safely excluded via `.gitignore`).
*   📁 **`final_videolar/`**: The target rendering directory storing ready-to-upload dynamic Shorts.
*   ⚙️ **`app.py` & `main_web.py`**: Handles API requests, OpenRouter calls, and schedules rendering pipelines.

---

## 🔒 Security & Local Exclusions

To ensure total code integrity:
*   **Keys and Configs (`.gitignore`):** Securely hides `.env` configurations, local API keys, Python environment binaries (`venv/`), raw download caches (`*.mp4`, `*.mp3`), and diagnostic output logs (`*.log`) from leaking to the public.

---

## 🚀 How to Set Up & Run

### 1. Prerequisites
*   **Python:** Install Python `3.10` or higher (make sure it is added to your environment variables PATH).
*   **FFmpeg:** Ensure FFmpeg is installed and added to your System Environment variables PATH.

### 2. Install Dependencies
Open your command terminal inside the project directory and run:
```bash
pip install -r requirements.txt
```

### 3. Add API Credentials
*   Obtain a free API Key from [OpenRouter](https://openrouter.ai).
*   Add the key to your `.env` file or paste it inside the `API_KEY` definition in `app.py`.

### 4. Boot Up the Dashboard
Double-click `run.bat` or run:
```bash
python launcher.pyw
```
Open the provided local URL in your browser and start crafting viral automated Shorts instantly!

---

## 👤 Developer Profile

This automation suite is designed and maintained by **Oğuz Emir Topuz**.

*   **Age:** 14
*   **Passions:** Football Tactical Analyst & Fullstack Software Developer.
*   **Connect:** [My GitHub Portfolio](https://github.com/oguzemirtopuz)
