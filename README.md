# 360° Video Processing Pipeline (Single Stream + ABR)

A robust, production-oriented video transcoding pipeline designed for **360° video feeds**. It automatically detects available **hardware acceleration** (NVIDIA/Apple/CPU) and converts raw footage into optimized HLS streams.

This repository contains two pipelines:

1. **`video_processor.py`** (Single Quality) — Fast, lightweight, preserves original resolution.
2. **`abr_processor.py`** (Adaptive Bitrate) — **Production Ready.** Generates 8K/4K/1080p ladders with a Master Playlist for auto-switching quality based on bandwidth.

---

## Features (Both Pipelines)

* **Auto Hardware Detection:** automatically selects the best encoder:
* `h264_nvenc` — NVIDIA GPUs (Windows / Linux)
* `h264_videotoolbox` — Apple Silicon (macOS)
* `libx264` — CPU fallback (Universal)


* **Dynamic GOP Calculation:** Probes input FPS to calculate an exact **2-second GOP** (`FPS * 2`), ensuring perfect seeking and no buffering loops.
* **Feed-Ready Outputs:** Generates HLS playlists (`.m3u8`) and a high-quality `poster.jpg` for UI previews.
* **JSON Output:** Prints a JSON object to `stdout` for easy Node.js/Backend integration.

---

## Prerequisites

### 1. Install FFmpeg

The script depends on a system-level FFmpeg binary.

* **Windows:** Download, extract, and add `bin` to PATH.
* **Linux:** `sudo apt install ffmpeg`
* **macOS:** `brew install ffmpeg`

### 2. Python Requirements

```bash
pip install ffmpeg-python

```

---

## Pipeline 1: Single Stream (`video_processor.py`)

**Use Case:** Quick previews, internal tools, or MVP where ABR is not yet needed.
**Behavior:** Maintains the original resolution (e.g., Input 4K  Output 4K).

### Usage

```bash
python video_processor.py <INPUT_FILE> <OUTPUT_DIRECTORY>

# Example
python video_processor.py ./raw/tour.mp4 ./public/videos/tour_001

```

### Output Structure

Creates a flat folder structure.

```plaintext
/public/videos/tour_001/
├── poster.jpg          # UI Thumbnail
├── index.m3u8          # Play this URL
├── segment_000.ts      # Video Chunk 1
├── segment_001.ts      # Video Chunk 2
└── ...

```

---

## Pipeline 2: Adaptive Bitrate (`abr_processor.py`)

**Use Case:** **Production.** Required for public feeds to support mobile (4G) vs. WiFi (Fiber).
**Behavior:** Analyzes input resolution and creates a "Ladder" of qualities (e.g., 4K, 1440p, 1080p).

* **Smart Ladder:** It will **never upscale**. If input is 4K, it generates [4K, 1080p, 720p]. It will *skip* 8K.
* **Master Playlist:** Generates a `master.m3u8` that links all versions together.

### Usage

```bash
python abr_processor.py <INPUT_FILE> <OUTPUT_DIRECTORY>

# Example
python abr_processor.py ./raw/tour.mp4 ./public/videos/tour_001

```

### Output Structure (Nested)

Creates a HLS Master structure.

```plaintext
/public/videos/tour_001/
├── poster.jpg           # UI Thumbnail
├── master.m3u8          # <--- GIVE THIS URL TO THE PLAYER
├── 4k/
│   ├── index.m3u8       # 4K Variant Playlist
│   └── seg_000.ts
├── 1080p/
│   ├── index.m3u8       # 1080p Variant Playlist
│   └── seg_000.ts
└── 720p/
    └── ...

```

---

## Backend Integration (Node.js Example)

Both scripts output JSON to `stdout` upon success. The ABR script includes extra details about which qualities were generated.

```javascript
const { spawn } = require('child_process');
const path = require('path');

// Choose your fighter: 'video_processor.py' OR 'abr_processor.py'
const script = 'abr_processor.py'; 
const input = path.resolve('./uploads/raw.mp4');
const output = path.resolve('./public/videos/stream_123');

const process = spawn('python', [script, input, output]);

process.stdout.on('data', (data) => {
  try {
    const result = JSON.parse(data.toString());
    
    if (result.status === 'success') {
        console.log('✅ Transcoding Complete');
        console.log('Poster:', result.poster_url);
        
        // Single Stream returns 'stream_url'
        // ABR Stream returns 'master_url' + 'qualities_generated' array
        console.log('Stream URL:', result.master_url || result.stream_url);
    }
  } catch (e) {
    // Ignore non-JSON logs
  }
});

process.stderr.on('data', (data) => {
    console.error('FFmpeg Log:', data.toString());
});

```

---

## Internals & Logic

### 1. Hardware Probing

At startup, both scripts run `ffmpeg -encoders`.

* **NVIDIA:** Uses `h264_nvenc` with `preset: p4` (Balanced VBR).
* **Apple Silicon:** Uses `h264_videotoolbox` with `allow_sw=1`.
* **CPU:** Uses `libx264` with `preset: veryfast` (Safe fallback).

### 2. Dynamic ABR Logic (ABR Processor Only)

The script probes the input video before processing.

* **Input:** 3840x2160 (4K)
* **Logic:**
* Is 8K (7680w) <= Input? **No.** (Skip 8K)
* Is 4K (3840w) <= Input? **Yes.** (Generate 4K)
* Is 1080p (1920w) <= Input? **Yes.** (Generate 1080p)


* **Result:** Efficient encoding without wasting CPU on impossible upscaling.

---

## Troubleshooting

**Issue: ABR Script only generated "original" folder**

* **Cause:** Input video was smaller than 720p (e.g., 480p source).
* **Behavior:** The script creates a fallback "original" quality to ensure at least one stream exists.

**Issue: Playback freezes every few seconds**

* **Cause:** GOP size mismatch.
* **Fix:** Ensure the script is correctly detecting the FPS. The logs will show: `User-Agent: VideoProcessor/1.0 Analysis: 30.00 FPS. Setting GOP to 60.`

**Issue: GPU not being used**

* **Cause:** Docker container or VPS lacks NVIDIA Drivers.
* **Fix:** The script automatically falls back to CPU. No action required, but transcoding will be slower.

---

## Design Principle

This pipeline prioritizes **Playback Correctness** over raw compression efficiency.
We force `sc_threshold=0` (disable scene detection) and strict Keyframe alignment to ensure **seamless switching** between qualities on mobile networks.
