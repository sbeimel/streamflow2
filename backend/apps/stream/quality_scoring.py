"""
Quality Scoring Module - MACstrom-inspired Reference-Bitrate Sigmoid Scoring

This module implements a more sophisticated quality scoring system based on
MACstrom's approach, which uses codec-aware reference bitrates and sigmoid curves
for better stream quality discrimination.
"""

import math
from typing import Dict, Optional

# Reference bitrates (kbps) for "good quality" per codec/resolution
# Based on industry standards and MACstrom's implementation
REFERENCE_BITRATES = {
    # H.264 / AVC
    ('h264', '4k'): 35000,
    ('h264', '1080p'): 8000,
    ('h264', '720p'): 4000,
    ('h264', 'sd'): 1500,

    # HEVC / H.265 (more efficient, needs less bitrate)
    ('hevc', '4k'): 16000,
    ('hevc', '1080p'): 4500,
    ('hevc', '720p'): 2500,
    ('hevc', 'sd'): 900,

    # AV1 (most efficient)
    ('av1', '4k'): 12000,
    ('av1', '1080p'): 3500,
    ('av1', '720p'): 2000,
    ('av1', 'sd'): 700,
}

# Resolution ceilings - maximum score per resolution tier
# Ensures resolution hierarchy is respected (1080p always beats 720p)
RESOLUTION_CEILINGS = {
    '4k': 100,
    '1080p': 90,
    '720p': 75,
    'sd': 55,
}

# Off-air detection threshold (kbps)
NOT_STREAMING_THRESHOLD = 200


def normalize_codec(codec: str) -> str:
    """Normalize codec name to standard format."""
    if not codec or codec == 'N/A':
        return 'unknown'
    codec_lower = codec.lower()
    if 'h265' in codec_lower or 'hevc' in codec_lower:
        return 'hevc'
    if 'h264' in codec_lower or 'avc' in codec_lower:
        return 'h264'
    if 'av1' in codec_lower:
        return 'av1'
    return 'unknown'


def classify_resolution(resolution: str) -> str:
    """Classify resolution into tier (4k, 1080p, 720p, sd)."""
    if not resolution or resolution == 'N/A' or 'x' not in resolution:
        return 'sd'
    try:
        _, height = map(int, resolution.split('x'))
        if height >= 2160:
            return '4k'
        elif height >= 1080:
            return '1080p'
        elif height >= 720:
            return '720p'
        else:
            return 'sd'
    except (ValueError, AttributeError):
        return 'sd'


def get_reference_bitrate(codec: str, resolution: str) -> int:
    """Get reference bitrate for codec/resolution combination."""
    normalized_codec = normalize_codec(codec)
    resolution_tier = classify_resolution(resolution)
    key = (normalized_codec, resolution_tier)
    if key in REFERENCE_BITRATES:
        return REFERENCE_BITRATES[key]
    fallback_key = ('h264', resolution_tier)
    return REFERENCE_BITRATES.get(fallback_key, 8000)


def sigmoid_adequacy(ratio: float) -> float:
    """
    Calculate adequacy score using sigmoid curve.
    Formula: 1 / (1 + exp(-3.5 × (ratio - 0.7)))
    """
    try:
        return 1.0 / (1.0 + math.exp(-3.5 * (ratio - 0.7)))
    except (OverflowError, ValueError):
        return 1.0 if ratio > 0.7 else 0.0


def calculate_fps_factor(fps: float) -> float:
    """
    FPS bonus/penalty factor.
    ≥48 fps: +8% bonus | 20-48 fps: neutral | <20 fps: -15% penalty
    """
    if fps >= 48:
        return 1.08
    elif fps >= 20:
        return 1.0
    else:
        return 0.85


def calculate_quality_score(bitrate: float, codec: str, resolution: str, fps: float = 25.0) -> int:
    """
    Calculate quality score using reference-bitrate sigmoid method (MACstrom-inspired).
    Returns score 0-100.
    """
    if bitrate < NOT_STREAMING_THRESHOLD:
        return 0
    ref_bitrate = get_reference_bitrate(codec, resolution)
    ratio = bitrate / ref_bitrate
    adequacy = sigmoid_adequacy(ratio)
    resolution_tier = classify_resolution(resolution)
    ceiling = RESOLUTION_CEILINGS.get(resolution_tier, 55)
    fps_factor = calculate_fps_factor(fps)
    return min(round(ceiling * adequacy * fps_factor), 100)


def calculate_quality_score_fallback(resolution: str, fps: float = 25.0) -> int:
    """Fallback scoring when bitrate is unavailable."""
    resolution_tier = classify_resolution(resolution)
    base_scores = {'4k': 80, '1080p': 65, '720p': 50, 'sd': 30}
    base_score = base_scores.get(resolution_tier, 30)
    return round(base_score * calculate_fps_factor(fps))


def calculate_stream_score_enhanced(
    stream_data: Dict,
    use_legacy_scoring: bool = False,
    legacy_weights: Optional[Dict] = None,
    avoid_h265: bool = False
) -> float:
    """
    Enhanced stream scoring using MACstrom-inspired reference-bitrate sigmoid method.

    Args:
        stream_data: Stream analysis data (bitrate_kbps, video_codec, resolution, fps, status)
        use_legacy_scoring: If True, use legacy linear scoring
        legacy_weights: Weights for legacy scoring
        avoid_h265: If True, apply 30% penalty to H.265/HEVC streams

    Returns:
        Score 0.0-1.0 (normalized for compatibility with existing code)
    """
    if stream_data.get('status') not in ['OK', 'Priority-Only']:
        return 0.0

    bitrate = stream_data.get('bitrate_kbps', 0)
    codec = stream_data.get('video_codec') or 'h264'
    resolution = stream_data.get('resolution', '0x0')
    fps = stream_data.get('fps', 25.0)

    # Fallback for streams without bitrate but with resolution/FPS
    if bitrate == 0 and resolution not in ['0x0', 'N/A', ''] and fps > 0:
        if use_legacy_scoring:
            return 0.40
        score = calculate_quality_score_fallback(resolution, fps)
        if avoid_h265 and normalize_codec(codec) == 'hevc':
            score *= 0.7
        return score / 100.0

    if use_legacy_scoring:
        weights = legacy_weights or {'bitrate': 0.40, 'resolution': 0.35, 'fps': 0.15, 'codec': 0.10}
        weights['avoid_h265'] = avoid_h265
        return _calculate_legacy_score(stream_data, weights)

    # Enhanced scoring
    quality_score = calculate_quality_score(bitrate, codec, resolution, fps)
    if avoid_h265 and normalize_codec(codec) == 'hevc':
        quality_score *= 0.7
    return quality_score / 100.0


def _calculate_legacy_score(stream_data: Dict, weights: Dict) -> float:
    """Legacy linear weighted scoring for backward compatibility."""
    score = 0.0

    bitrate = stream_data.get('bitrate_kbps', 0)
    if bitrate > 0:
        score += min(bitrate / 8000, 1.0) * weights.get('bitrate', 0.40)

    resolution = stream_data.get('resolution', 'N/A')
    resolution_score = 0.0
    if 'x' in str(resolution):
        try:
            _, height = map(int, resolution.split('x'))
            if height >= 1080:
                resolution_score = 1.0
            elif height >= 720:
                resolution_score = 0.7
            elif height >= 576:
                resolution_score = 0.5
            else:
                resolution_score = 0.3
        except (ValueError, AttributeError):
            pass
    score += resolution_score * weights.get('resolution', 0.35)

    fps = stream_data.get('fps', 0)
    if fps > 0:
        score += min(fps / 60, 1.0) * weights.get('fps', 0.15)

    codec = stream_data.get('video_codec', '').lower()
    codec_score = 0.0
    prefer_h265 = weights.get('prefer_h265', True)
    avoid_h265 = weights.get('avoid_h265', False)
    if codec:
        if 'h265' in codec or 'hevc' in codec:
            codec_score = 0.5 if avoid_h265 else (1.0 if prefer_h265 else 0.8)
        elif 'h264' in codec or 'avc' in codec:
            codec_score = 1.0 if avoid_h265 else (0.8 if prefer_h265 else 0.8)
        elif codec != 'n/a':
            codec_score = 0.5
    score += codec_score * weights.get('codec', 0.10)

    return round(score, 2)
