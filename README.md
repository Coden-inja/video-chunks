# 360° Video Processing Pipeline (HLS + GPU)

A robust, production-oriented video transcoding pipeline designed for **360° video feeds**.  
It converts raw MP4 footage into optimized **HLS adaptive bitrate streams**, automatically detects available **hardware acceleration**, and adapts encoding parameters to the source video’s framerate.

The goal is **predictable playback**, **fast seeking**, and **safe server-side execution** across environments.

---

## Features

### Auto Hardware Detection
Automatically selects the best available encoder:

- `h264_nvenc` — NVIDIA GPUs (Windows / Linux)
- `h264_videotoolbox` — Apple Silicon (M1 / M2 / M3 on macOS)
- `libx264` — CPU fallback (universal, always available)

No flags or configuration needed from the user.

---

### Dynamic GOP Calculation
The script probes the input video’s actual FPS (24, 30, 60, etc.) and computes an exact **Group of Pictures (GOP)** size.

Target:
- **2-second HLS segments**
- Perfect keyframe alignment

Formula:
- `GOP_SIZE = round(FPS * 2)`

This prevents broken seeks, stuttering, and rebuffering on slow networks.

---

### Feed-Ready Outputs
In one pass, the script generates:

- `index.m3u8` — HLS playlist (ready for Three.js / Video.js)
- `poster.jpg` — high-quality first frame for UI previews

No extra processing step required.

---

### JSON Output for Backend Integration
On success, the script prints a **JSON object to stdout**, making it easy to integrate with:

- Node.js APIs
- Go services
- Job queues / workers
- Serverless pipelines

---

## Prerequisites

### 1. Install FFmpeg
The script depends on a system-level FFmpeg binary.

**Windows**
- Download FFmpeg
- Extract it
- Add the `bin` folder to your system PATH

**macOS**
```bash
brew install ffmpeg
```
**Linux (Ubuntu / Debian)**
```bash
sudo apt install ffmpeg
```
Verify installation:
```bash
ffmpeg -version
```
---

### 2. Python Requirements
Install the Python wrapper used by the script:

```bash
pip install ffmpeg-python
```
---

## Usage

### Option 1: Command Line (CLI)
Run manually or via cron / job runner.

```bash
# Syntax:
# python video_processor.py <INPUT_FILE> <OUTPUT_DIRECTORY>

python video_processor.py ./raw_footage/kitchen_tour.mp4 ./public/videos/tour_001
```
---

### Option 2: Integration with Node.js / Backend
Because the script outputs JSON to stdout, it can be spawned directly from your backend.

```js
const { spawn } = require('child_process');
const path = require('path');

const input = path.resolve('./uploads/raw.mp4');
const output = path.resolve('./public/stream_123');

const process = spawn('python', ['video_processor.py', input, output]);

process.stdout.on('data', (data) => {
  try {
    const result = JSON.parse(data.toString());
    console.log('Transcoding Success!', result);
    // Save result.hls_url to database
  } catch (e) {
    console.log('Log:', data.toString());
  }
});
```
---

## Output Structure

The script creates the output directory and generates:

```plaintext
/public/videos/tour_001/
├── poster.jpg          # High-quality first frame (UI preview)
├── index.m3u8          # HLS playlist
├── segment_000.ts      # Video chunk 1
├── segment_001.ts      # Video chunk 2
└── ...
```
---

## How It Works (Internals)

### 1. Hardware Probing
At startup, the script runs:

```bash
ffmpeg -encoders
```
Based on available encoders:

- NVIDIA detected  
  - Uses NVENC
  - Preset: `p4` (balanced VBR speed/quality)

- Apple VideoToolbox detected  
  - Enables `allow_sw=1`
  - Allows hybrid hardware/software encoding

- CPU only  
  - Uses `libx264`
  - Preset: `veryfast` to avoid server overload

This guarantees the job always completes, even without GPU support.

---

### 2. HLS Mathematics
HLS requires **keyframes to align exactly with segment boundaries**.

Example:
- Video FPS: 30
- Target segment length: 2 seconds
- Required GOP: 60 frames

Result:
- Instant seeking
- No black frames
- Stable playback under network pressure

---

## Troubleshooting

### Error: `FileNotFoundError: [WinError 2] The system cannot find the file specified`
**Cause**
- FFmpeg is not installed or not in PATH

**Fix**
- Run:
  ```bash
  ffmpeg -version
  ```
- Reinstall FFmpeg if the command fails

---

### Error: `AttributeError: 'NoneType' object has no attribute 'group'`
**Cause**
- Input file is invalid or corrupted

**Fix**
- Verify the file plays correctly in VLC before processing

---

### Issue: GPU not being used
**Cause**
- Driver issues
- FFmpeg build lacks NVENC support

**Fix**
- No action required
- The script automatically falls back to CPU (`libx264`)
- Processing will complete, but slower

---

## Design Principle (Non-Negotiable)

This pipeline prioritizes:

- Deterministic output
- Safe fallbacks
- Playback correctness over raw quality
- Backend reliability over clever hacks

In video processing, **predictability beats optimization**.
