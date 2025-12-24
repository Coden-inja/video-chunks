import ffmpeg
import os
import sys
import json
import logging
import platform
import subprocess
import shutil

# --- REFERENCE STANDARDS ---
# We define standard tier targets here. 
# This is NOT a hardcoded instruction list, but a "Menu" of options.
# The script will dynamically pick from this menu based on the input video.
REFERENCE_TIERS = [
    {"name": "8k",    "width": 7680, "height": 4320, "bitrate": "40000k"}, 
    {"name": "4k",    "width": 3840, "height": 2160, "bitrate": "18000k"},
    {"name": "1440p", "width": 2560, "height": 1440, "bitrate": "10000k"},
    {"name": "1080p", "width": 1920, "height": 1080, "bitrate": "5000k"},
    {"name": "720p",  "width": 1280, "height": 720,  "bitrate": "2500k"}
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class ABRVideoProcessor:
    def __init__(self):
        self.hardware_config = self._detect_hardware()

    def _detect_hardware(self):
        """Scans system for GPU acceleration"""
        try:
            res = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True)
            output = res.stdout
        except:
            return {'c:v': 'libx264', 'preset': 'veryfast'}

        if 'h264_nvenc' in output:
            return {'c:v': 'h264_nvenc', 'preset': 'p4', 'rc': 'vbr'}
        if platform.system() == 'Darwin' and 'h264_videotoolbox' in output:
            return {'c:v': 'h264_videotoolbox', 'q': 60, 'allow_sw': 1}
        
        return {'c:v': 'libx264', 'preset': 'veryfast'}

    def _analyze_input(self, input_path):
        """Probes the input video to get exact dimensions and GOP target"""
        try:
            probe = ffmpeg.probe(input_path)
            video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            width = int(video_stream['width'])
            height = int(video_stream['height'])
            
            avg_frame_rate = video_stream.get('avg_frame_rate', '30/1')
            num, den = map(int, avg_frame_rate.split('/'))
            fps = num / den if den > 0 else 30
            
            return {
                "width": width, 
                "height": height, 
                "gop": int(round(fps * 2))
            }
        except Exception as e:
            logger.error(f"Probe failed: {e}")
            sys.exit(1)

    def _generate_ladder(self, input_w, input_h):
        """
        Dynamically constructs the transcoding ladder.
        Logic: Include any standard tier that is <= input resolution.
        """
        ladder = []
        
        # 1. Filter standard tiers
        for tier in REFERENCE_TIERS:
            if tier['width'] <= input_w:
                ladder.append(tier)
        
        # 2. Edge Case: If input is smaller than 720p (e.g. 480p source)
        # We ensure at least the original resolution is preserved
        if not ladder:
             ladder.append({
                 "name": "original", 
                 "width": input_w, 
                 "height": input_h, 
                 "bitrate": "1000k"
             })
             
        return ladder

    def process(self, input_path, output_root):
        if not os.path.exists(input_path):
            logger.error("File not found.")
            return

        # 1. Clean & Setup
        vid_id = os.path.splitext(os.path.basename(input_path))[0]
        base_dir = os.path.join(output_root, vid_id)
        if os.path.exists(base_dir): shutil.rmtree(base_dir)
        os.makedirs(base_dir, exist_ok=True)

        # 2. Analyze & Plan
        info = self._analyze_input(input_path)
        ladder = self._generate_ladder(info['width'], info['height'])
        
        logger.info(f"🚀 Input: {info['width']}x{info['height']} | Plan: {[t['name'] for t in ladder]}")
        
        master_playlist_content = "#EXTM3U\n#EXT-X-VERSION:3\n"

        # 3. Generate Poster
        poster_path = os.path.join(base_dir, 'poster.jpg')
        (
            ffmpeg.input(input_path)
            .filter('select', 'gte(n,0)')
            .output(poster_path, vframes=1, q=2, loglevel="error")
            .run(overwrite_output=True)
        )

        # 4. Execute Ladder
        for variant in ladder:
            variant_name = variant['name']
            variant_dir = os.path.join(base_dir, variant_name)
            os.makedirs(variant_dir, exist_ok=True)
            output_m3u8 = os.path.join(variant_dir, 'index.m3u8')
            
            logger.info(f"   • Processing {variant_name}...")
            
            stream = ffmpeg.input(input_path)
            stream = ffmpeg.output(
                stream,
                output_m3u8,
                format='hls',
                hls_time=2,
                hls_list_size=0,
                hls_segment_filename=os.path.join(variant_dir, 'seg_%03d.ts'),
                vf=f"scale={variant['width']}:-2", 
                **{'b:v': variant['bitrate'], 'maxrate': variant['bitrate']},
                **{'bufsize': str(int(variant['bitrate'].replace('k','')) * 2) + 'k'},
                g=info['gop'],
                keyint_min=info['gop'],
                sc_threshold=0,
                **{'c:a': 'aac', 'b:a': '128k'},
                **self.hardware_config
            )
            stream.run(overwrite_output=True, quiet=True)

            bandwidth = int(variant['bitrate'].replace('k', '')) * 1000
            master_playlist_content += (
                f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={variant['width']}x{variant['height']}\n"
                f"{variant_name}/index.m3u8\n"
            )

        # 5. Write Master
        with open(os.path.join(base_dir, 'master.m3u8'), 'w') as f:
            f.write(master_playlist_content)
            
        print(json.dumps({
            "status": "success",
            "stream_url": f"/videos/{vid_id}/master.m3u8",
            "poster_url": f"/videos/{vid_id}/poster.jpg"
        }))

if __name__ == "__main__":
    ABRVideoProcessor().process(sys.argv[1], sys.argv[2])
