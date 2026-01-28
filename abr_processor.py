import ffmpeg
import os
import sys
import json
import logging
import platform
import subprocess
import shutil

# --- CONFIGURATION ---
# The menu of standard resolutions we support.
# The script picks from this list based on input quality.
REFERENCE_TIERS = [
    {"name": "8k",    "width": 7680, "height": 3840, "bitrate": "35000k"}, 
    {"name": "4k",    "width": 3840, "height": 1920, "bitrate": "16000k"}, 
    {"name": "1440p", "width": 2560, "height": 1280, "bitrate": "9000k"}, 
    {"name": "1080p", "width": 1920, "height": 960,  "bitrate": "4500k"},  
    {"name": "720p",  "width": 1280, "height": 640,  "bitrate": "2000k"}, 
    {"name": "480p",  "width": 854,  "height": 427,  "bitrate": "900k"}   
]   

# Logging Setup: Send logs to STDERR so they don't break JSON output on STDOUT
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self):
        self.hardware_config = self._detect_hardware()

    def _detect_hardware(self):
        """Scans the VPS for GPU acceleration capabilities"""
        try:
            res = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True)
            output = res.stdout
        except Exception:
            logger.warning("FFmpeg not found or error. Defaulting to CPU.")
            return {'c:v': 'libx264', 'preset': 'veryfast'}

        # 1. NVIDIA GPU (Common in AWS/GCP instances)
        if 'h264_nvenc' in output:
            logger.info("Hardware: NVIDIA GPU (NVENC) detected.")
            return {'c:v': 'h264_nvenc', 'preset': 'p4', 'rc': 'vbr'}
        
        # 2. Apple Silicon (If hosting on Mac Mini servers)
        if platform.system() == 'Darwin' and 'h264_videotoolbox' in output:
            logger.info("Hardware: Apple Silicon detected.")
            return {'c:v': 'h264_videotoolbox', 'q': 60, 'allow_sw': 1}
        
        # 3. CPU Fallback (Standard DigitalOcean/Linode Droplet)
        logger.info("Hardware: No GPU detected. Using CPU (libx264).")
        return {'c:v': 'libx264', 'preset': 'veryfast'}

    def _analyze_input(self, input_path):
        """Probes the input video for resolution and framerate"""
        try:
            probe = ffmpeg.probe(input_path)
            video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            width = int(video_stream['width'])
            height = int(video_stream['height'])
            
            # Calculate exact framerate for GOP
            avg_frame_rate = video_stream.get('avg_frame_rate', '30/1')
            num, den = map(int, avg_frame_rate.split('/'))
            fps = num / den if den > 0 else 30
            
            return {
                "width": width, 
                "height": height, 
                "gop": int(round(fps * 2)) # 2-second GOP target
            }
        except Exception as e:
            logger.error(f"Probe failed: {e}")
            sys.exit(1)

    def _generate_ladder(self, input_w, input_h):
        """Constructs the transcoding plan based on input resolution"""
        ladder = []
        for tier in REFERENCE_TIERS:
            # logic: Only generate tiers that are smaller or equal to input
            if tier['width'] <= input_w:
                ladder.append(tier)
        ladder.sort(key=lambda t: t['width'])
        # Fallback for weird low-res videos
        if not ladder:
             ladder.append({"name": "original", "width": input_w, "height": input_h, "bitrate": "1000k"})
        
        return ladder

    def process(self, input_path, output_root):
        if not os.path.exists(input_path):
            logger.error(f"File not found: {input_path}")
            sys.exit(1)

        # 1. Setup Directories
        vid_id = os.path.splitext(os.path.basename(input_path))[0]
        base_dir = os.path.join(output_root, vid_id)
        
        if os.path.exists(base_dir): shutil.rmtree(base_dir) # Clean overwrite
        os.makedirs(base_dir, exist_ok=True)

        # 2. Analyze
        info = self._analyze_input(input_path)
        ladder = self._generate_ladder(info['width'], info['height'])
        
        logger.info(f"🎬 Processing {vid_id} [{info['width']}x{info['height']}] -> {[t['name'] for t in ladder]}")
        
        master_playlist_content = "#EXTM3U\n#EXT-X-VERSION:3\n"

        try:
            # 3. Generate Poster (Thumbnail)
            poster_path = os.path.join(base_dir, 'poster.jpg')
            (
                ffmpeg.input(input_path)
                .filter('select', 'gte(n,0)')
                .output(poster_path, vframes=1, q=2, loglevel="error")
                .run(overwrite_output=True)
            )

            # 4. Transcode ABR Ladder
            for variant in ladder:
                variant_name = variant['name']
                variant_dir = os.path.join(base_dir, variant_name)
                os.makedirs(variant_dir, exist_ok=True)
                
                output_m3u8 = os.path.join(variant_dir, 'index.m3u8')
                
                logger.info(f"   • Transcoding: {variant_name}...")
                
                # Build FFmpeg Pipeline
                stream = ffmpeg.input(input_path)
                stream = ffmpeg.output(
                    stream,
                    output_m3u8,
                    format='hls',
                    hls_time=2,
                    hls_list_size=0,         # Keep all chunks
                    hls_segment_filename=os.path.join(variant_dir, 'seg_%03d.ts'),
                    vf=f"scale={variant['width']}:-2", # Smart scaling
                    **{'b:v': variant['bitrate'], 'maxrate': variant['bitrate']},
                    **{'bufsize': str(int(variant['bitrate'].replace('k','')) * 2) + 'k'},
                    g=info['gop'],           # Perfect Keyframe alignment
                    keyint_min=info['gop'],
                    sc_threshold=0,          # No scene detection (Crucial for ABR)
                    **{'c:a': 'aac', 'b:a': '128k'},
                    **self.hardware_config   # GPU/CPU flags injected here
                )
                stream.run(overwrite_output=True, quiet=True)

                # Append to Master Playlist memory
                bandwidth = int(variant['bitrate'].replace('k', '')) * 1000
                master_playlist_content += (
                    f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={variant['width']}x{variant['height']}\n"
                    f"{variant_name}/index.m3u8\n"
                )

            # 5. Write Master Playlist
            with open(os.path.join(base_dir, 'master.m3u8'), 'w') as f:
                f.write(master_playlist_content)
            
            # 6. OUTPUT JSON (This is what your Node.js backend reads)
            result = {
                "status": "success",
                "video_id": vid_id,
                "folder_path": base_dir,
                "master_url": f"/videos/{vid_id}/master.m3u8",
                "poster_url": f"/videos/{vid_id}/poster.jpg",
                "qualities_generated": [t['name'] for t in ladder]
            }
            print(json.dumps(result)) # Print to STDOUT

        except ffmpeg.Error as e:
            logger.error(f"FFmpeg Error: {e.stderr.decode() if e.stderr else str(e)}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Script Error: {str(e)}")
            sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        logger.error("Usage: python video_processor.py <input_file> <output_root_dir>")
        sys.exit(1)
    
    VideoProcessor().process(sys.argv[1], sys.argv[2])
