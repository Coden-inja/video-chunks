import ffmpeg
import os
import sys
import json
import logging
import platform
import subprocess
import math

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self):
        self.hardware_config = self._detect_hardware()

    def _detect_hardware(self):
        """
        Scans the system for available GPU accelerators.
        Returns a dictionary of input/output codec flags.
        """
        system = platform.system()
        logger.info(f"System detected: {system}")
        
        try:
            # Run ffmpeg -encoders to check availability
            result = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True)
            output = result.stdout
        except FileNotFoundError:
            logger.error("❌ FFmpeg not found. Please install FFmpeg and add it to PATH.")
            sys.exit(1)

        # 1. NVIDIA GPU (Windows/Linux)
        if 'h264_nvenc' in output:
            logger.info("Hardware: NVIDIA GPU (NVENC) detected.")
            return {
                'c:v': 'h264_nvenc',
                'preset': 'p4',       # Optimized for speed/quality balance
                'rc': 'vbr',
                'cq': 23,             # Constant Quality
                'pix_fmt': 'yuv420p'
            }
        
        # 2. Apple Silicon / Intel Mac (macOS)
        if system == 'Darwin' and 'h264_videotoolbox' in output:
            logger.info("Hardware: Apple Silicon/Intel (VideoToolbox) detected.")
            return {
                'c:v': 'h264_videotoolbox',
                'q': 60,              # Quality scale 0-100
                'allow_sw': 1,        # Allow fallback if hardware is busy
                'pix_fmt': 'yuv420p'
            }
        
        # 3. AMD GPU (Linux/Windows)
        if 'h264_amf' in output:
             logger.info("Hardware: AMD GPU (AMF) detected.")
             return {'c:v': 'h264_amf', 'usage': 'transcoding'}

        # 4. Fallback: CPU
        logger.warning("No GPU detected. Falling back to CPU (libx264).")
        return {
            'c:v': 'libx264',
            'preset': 'veryfast',  # Fast encoding for CPU
            'crf': 23,             # Standard Web Quality
            'pix_fmt': 'yuv420p'
        }

    def _analyze_video(self, input_path):
        """
        Probes video metadata to calculate exact GOP size for HLS.
        Ensures perfect 2-second chunks regardless of FPS (24, 30, 60).
        """
        try:
            probe = ffmpeg.probe(input_path)
            video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            
            if not video_stream:
                raise ValueError("No video stream found in file.")

            # Calculate FPS
            # format is usually "30000/1001" or "30/1"
            avg_frame_rate = video_stream.get('avg_frame_rate', '30/1')
            num, den = map(int, avg_frame_rate.split('/'))
            fps = num / den if den > 0 else 30

            # Calculate GOP (Group of Pictures) for 2-second segments
            # HLS requires keyframes to match segment duration perfectly
            gop_size = int(round(fps * 2))

            logger.info(f"🔍 Analysis: {fps:.2f} FPS. Setting GOP to {gop_size} frames (2.0s).")

            return {
                'g': gop_size,
                'keyint_min': gop_size,
                'sc_threshold': 0  # Disable scene cut detection for consistent HLS chunks
            }

        except Exception as e:
            logger.warning(f"⚠️  Probe failed ({e}). using generic fallback settings.")
            return {
                'force_key_frames': 'expr:gte(t,n_forced*2)',
                'sc_threshold': 0
            }

    def process(self, input_path, output_dir):
        """
        Main Pipeline: Input -> [Analysis] -> [Poster] -> [HLS Stream] -> Output
        """
        if not os.path.exists(input_path):
            logger.error(f"File not found: {input_path}")
            return

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.splitext(os.path.basename(input_path))[0]
        
        hls_output = os.path.join(output_dir, 'index.m3u8')
        poster_output = os.path.join(output_dir, 'poster.jpg')

        # Get Dynamic Settings
        stream_settings = self._analyze_video(input_path)
        encoder_settings = self.hardware_config

        input_stream = ffmpeg.input(input_path)

        try:
            logger.info(f"Processing: {filename}...")

            # --- STEP 1: Generate Poster (High Quality First Frame) ---
            # We run this separately to ensure it doesn't block the main transcode
            (
                input_stream
                .filter('select', 'gte(n,0)')
                .output(poster_output, vframes=1, q=2, loglevel="error")
                .run(overwrite_output=True)
            )
            logger.info("✅ Poster generated.")

            # --- STEP 2: Generate HLS Stream ---
            # Merging all dynamic settings into one dictionary
            output_args = {
                'format': 'hls',
                'hls_time': 2,
                'hls_list_size': 0,     # Keep all segments
                'hls_segment_filename': os.path.join(output_dir, 'segment_%03d.ts'),
                'c:a': 'aac',           # Audio Codec (Universal)
                'b:a': '128k',
                **stream_settings,      # Inject GOP/FPS settings
                **encoder_settings      # Inject GPU/CPU settings
            }

            (
                input_stream
                .output(hls_output, **output_args)
                .run(overwrite_output=True)
            )
            
            logger.info(f"✅ Transcoding Complete! Output: {output_dir}")
            
            # Print JSON result for your API to parse
            result = {
                "status": "success",
                "hls_url": f"/videos/{os.path.basename(output_dir)}/index.m3u8",
                "poster_url": f"/videos/{os.path.basename(output_dir)}/poster.jpg"
            }
            print(json.dumps(result))

        except ffmpeg.Error as e:
            logger.error(f"❌ FFmpeg Error: {e.stderr.decode() if e.stderr else str(e)}")
            sys.exit(1)

# --- CLI Entry Point ---
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nUsage: python video_processor.py <input_file> <output_directory>")
        print("Example: python video_processor.py ./raw/tour.mp4 ./public/videos/tour_01\n")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_folder = sys.argv[2]
    
    processor = VideoProcessor()
    processor.process(input_file, output_folder)
