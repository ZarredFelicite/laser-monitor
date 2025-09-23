#!/usr/bin/env python3
"""
Visual Prompts Configuration for tests

This file is used by pytest to load a bbox visual prompt configuration
for the sample images in the tests/ directory.
"""

# Reference image path (not strictly required for bbox mode, kept for completeness)
refer_image = r"tests/test1.jpg"

# A simple prompt region (normalized coords) roughly centered; tests set mode=bbox
# so the heuristic path uses this region without loading AI models.
# Two ROIs around the stack light near the center-right of the frame.
# These are approximate normalized coordinates sized to include both
# the red (top) and orange (middle) segments for indicator composite logic.
visual_prompts = [[0.646875, 0.41388888888888886, 0.6598958333333333, 0.4703703703703704], [0.05572916666666667, 0.44814814814814813, 0.0625, 0.4759259259259259]]

# Optional metadata
image_dimensions = None
