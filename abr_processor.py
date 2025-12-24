import ffmpeg
import os
import sys
import json
import logging
import platform
import subprocess
import shutil

# --- CONFIGURATION ---
# The "Ladder": Define your ABR qualities here
ABR_LADDER = [
    {"name": "1080p", "width": 1920, "height": 1080, "bitrate": "4500k"},
    {"name": "720p",  "width": 1280, "height": 720,  "bitrate": "2500k"},
    {"name": "480p",  "width": 854,  "height": 480,  "bitrate": "1000k"}
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

    def _get_gop_size(self, input_path):
        """Calculates GOP for exactly 2.0s segments"""
        try:
            probe = ffmpeg.probe(input_path)
            video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            avg_frame_rate = video_stream.get('avg_frame_rate', '30/1')
            num, den = map(int, avg_frame_rate.split('/'))
            fps = num / den if den > 0 else 30
            return int(round(fps * 2)) # 2 seconds
        except:
            return 60 # Safe fallback

    def process(self, input_path, output_root):
        if not os.path.exists(input_path):
            logger.error("File not found.")
            return

        # 1. Setup Folders
        vid_id = os.path.splitext(os.path.basename(input_path))[0]
        base_dir = os.path.join(output_root, vid_id)
        os.makedirs(base_dir, exist_ok=True)

        gop_size = self._get_gop_size(input_path)
        master_playlist_content = "#EXTM3U\n#EXT-X-VERSION:3\n"
        
        logger.info(f"🚀 Processing: {vid_id} (Hardware: {self.hardware_config['c:v']})")

        # 2. Generate Poster (Once)
        poster_path = os.path.join(base_dir, 'poster.jpg')
        (
            ffmpeg.input(input_path)
            .filter('select', 'gte(n,0)')
            .output(poster_path, vframes=1, q=2, loglevel="error")
            .run(overwrite_output=True)
        )

        # 3. Iterate through ABR Ladder
        for variant in ABR_LADDER:
            variant_name = variant['name']
            variant_dir = os.path.join(base_dir, variant_name)
            os.makedirs(variant_dir, exist_ok=True)
            
            output_m3u8 = os.path.join(variant_dir, 'index.m3u8')
            
            # Scale video (Resize)
            # Note: We use scale=-2 to keep aspect ratio even if height is slightly off
            logger.info(f"   • Transcoding {variant_name}...")
            
            # Build FFmpeg command
            stream = ffmpeg.input(input_path)
            stream = ffmpeg.output(
                stream,
                output_m3u8,
                format='hls',
                hls_time=2,
                hls_list_size=0,
                hls_segment_filename=os.path.join(variant_dir, 'seg_%03d.ts'),
                # ABR Specifics
                vf=f"scale={variant['width']}:-2",
                **{'b:v': variant['bitrate']}, # Target Bitrate
                **{'maxrate': variant['bitrate']}, 
                **{'bufsize': str(int(variant['bitrate'].replace('k','')) * 2) + 'k'},
                # Common HLS settings
                g=gop_size,
                keyint_min=gop_size,
                sc_threshold=0,
                **{'c:a': 'aac', 'b:a': '128k'},
                **self.hardware_config
            )
            stream.run(overwrite_output=True, quiet=True)

            # Append to Master Playlist logic
            # We assume a path relative to master.m3u8
            # BANDWIDTH is bits/sec, so 4500k -> 4500000
            bandwidth = int(variant['bitrate'].replace('k', '')) * 1000
            master_playlist_content += (
                f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={variant['width']}x{variant['height']}\n"
                f"{variant_name}/index.m3u8\n"
            )

        # 4. Write Master Playlist
        with open(os.path.join(base_dir, 'master.m3u8'), 'w') as f:
            f.write(master_playlist_content)

        logger.info("✅ Done.")
        
        # Return easy-to-use JSON
        print(json.dumps({
            "status": "success",
            "video_id": vid_id,
            "stream_url": f"/videos/{vid_id}/master.m3u8",
            "poster_url": f"/videos/{vid_id}/poster.jpg"
        }))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python abr_processor.py <input> <output_root>")
        sys.exit(1)
    ABRVideoProcessor().process(sys.argv[1], sys.argv[2])
