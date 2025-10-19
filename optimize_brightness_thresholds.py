#!/usr/bin/env python3
"""
Optimize brightness threshold ratios using grid search.

Performs a sweep over different threshold ratio combinations to find
the configuration that maximizes detection accuracy against expected results.
"""

import os
import sys
from pathlib import Path
import json
import itertools
from typing import List, Tuple, Dict, Any
import warnings

try:
    import cv2
    import numpy as np
except Exception as e:
    print(f"Required packages unavailable: {e}")
    sys.exit(1)

from config.config import ConfigManager
from laser_monitor import LaserMonitor


class MachineExpectationWarning(Warning):
    """Non-fatal expectation mismatch for secondary machines"""
    pass


def setup_monitor_with_ratios(ratios: List[List[float]]) -> LaserMonitor:
    """Create monitor with specific threshold ratios"""
    cm = ConfigManager()
    cfg_path = Path("tests/test_brightness.config.py").resolve()
    config = cm.load_config(str(cfg_path))
    
    # Force bbox mode and brightness settings
    config.detection.mode = "bbox"
    config.detection.indicator_mode = False
    config.detection.use_brightness_threshold = True
    config.detection.brightness_threshold_ratios = ratios
    config.display.display_video = False
    config.output.save_detections = False
    config.output.save_screenshots = False
    config.logging.log_to_file = False
    config.logging.log_level = "ERROR"
    config.detection.bbox_force_detection = False
    config.alerts.email_alerts = False
    config.alerts.sms_alerts = False
    
    return LaserMonitor(config)


def evaluate_ratios(ratios: List[List[float]], test_images: List[Path], verbose: bool = False) -> Tuple[float, int, int]:
    """
    Evaluate a specific ratio configuration against all test images.
    
    Returns:
        (accuracy, passed_count, total_count)
    """
    monitor = setup_monitor_with_ratios(ratios)
    
    total_tests = 0
    passed_tests = 0
    
    for img_path in test_images:
        # Load expected results
        expected_path = img_path.with_suffix(".expected.json")
        if not expected_path.exists():
            continue
            
        with expected_path.open("r") as f:
            expected = json.load(f)
        
        # Load and process image
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
        
        h, w = frame.shape[:2]
        detections = monitor.detect_objects(frame)
        
        # Build detection map by index (machine_0, machine_1, ...)
        det_map = {}
        for idx, det in enumerate(detections):
            machine_id = f"machine_{idx}"
            det_map[machine_id] = det.class_name
        
        # Extract machines dict from expected format
        machines = expected.get("machines", expected)
        
        # Check against expectations
        for machine_id, expected_class in machines.items():
            total_tests += 1
            detected_class = det_map.get(machine_id, "machine_off")
            
            if detected_class == expected_class:
                passed_tests += 1
            elif verbose:
                print(f"  {img_path.name} {machine_id}: expected {expected_class}, got {detected_class}")
    
    accuracy = (passed_tests / total_tests * 100) if total_tests > 0 else 0.0
    return accuracy, passed_tests, total_tests


def grid_search(
    test_images: List[Path],
    top_range: Tuple[float, float, float],
    mid_range: Tuple[float, float, float],
    num_rois: int = 2
) -> List[Tuple[float, List[List[float]]]]:
    """
    Perform grid search over threshold ratio space.
    
    Args:
        test_images: List of test image paths
        top_range: (start, stop, step) for top section ratios
        mid_range: (start, stop, step) for middle section ratios
        num_rois: Number of ROIs (default 2)
    
    Returns:
        List of (accuracy, ratios) tuples, sorted by accuracy descending
    """
    # Generate ratio candidates
    top_start, top_stop, top_step = top_range
    mid_start, mid_stop, mid_step = mid_range
    
    top_values = list(np.arange(top_start, top_stop + top_step, top_step))
    mid_values = list(np.arange(mid_start, mid_stop + mid_step, mid_step))
    
    print(f"Grid search parameters:")
    print(f"  Top ratios: {top_values}")
    print(f"  Mid ratios: {mid_values}")
    print(f"  ROIs: {num_rois}")
    print(f"  Total combinations per ROI: {len(top_values) * len(mid_values)}")
    
    # For simplicity, try same ratios for all ROIs first
    # Then try independent optimization if needed
    results = []
    
    total_combos = len(top_values) * len(mid_values)
    combo_idx = 0
    
    for top_ratio in top_values:
        for mid_ratio in mid_values:
            combo_idx += 1
            # Use same ratios for all ROIs
            ratios = [[float(top_ratio), float(mid_ratio)] for _ in range(num_rois)]
            
            accuracy, passed, total = evaluate_ratios(ratios, test_images)
            results.append((accuracy, ratios))
            
            print(f"[{combo_idx}/{total_combos}] Ratios: {ratios[0]} -> Accuracy: {accuracy:.1f}% ({passed}/{total})")
    
    # Sort by accuracy descending
    results.sort(key=lambda x: x[0], reverse=True)
    return results


def independent_grid_search(
    test_images: List[Path],
    top_range: Tuple[float, float, float],
    mid_range: Tuple[float, float, float],
    num_rois: int = 2
) -> List[Tuple[float, List[List[float]]]]:
    """
    Perform grid search with independent ratios per ROI.
    
    This can be computationally expensive for many ROIs.
    """
    top_start, top_stop, top_step = top_range
    mid_start, mid_stop, mid_step = mid_range
    
    top_values = list(np.arange(top_start, top_stop + top_step, top_step))
    mid_values = list(np.arange(mid_start, mid_stop + mid_step, mid_step))
    
    # Generate all combinations for a single ROI
    single_roi_combos = list(itertools.product(top_values, mid_values))
    
    # Generate all combinations across ROIs
    all_combos = list(itertools.product(single_roi_combos, repeat=num_rois))
    
    print(f"Independent grid search parameters:")
    print(f"  Top ratios: {top_values}")
    print(f"  Mid ratios: {mid_values}")
    print(f"  ROIs: {num_rois}")
    print(f"  Total combinations: {len(all_combos)}")
    print(f"  WARNING: This may take a long time!")
    
    results = []
    
    for combo_idx, combo in enumerate(all_combos, 1):
        ratios = [[float(top), float(mid)] for top, mid in combo]
        
        accuracy, passed, total = evaluate_ratios(ratios, test_images)
        results.append((accuracy, ratios))
        
        if combo_idx % 10 == 0 or combo_idx == len(all_combos):
            print(f"[{combo_idx}/{len(all_combos)}] Ratios: {ratios} -> Accuracy: {accuracy:.1f}% ({passed}/{total})")
    
    results.sort(key=lambda x: x[0], reverse=True)
    return results


def main():
    # Load test images
    test_images = sorted(Path("tests").glob("test*.jpg"))
    
    if not test_images:
        print("No test images found in tests/")
        return 1
    
    print(f"Found {len(test_images)} test images")
    print()
    
    # Define search space
    # Start with coarse grid, then refine around best results
    TOP_RANGE = (1.0, 2.5, 0.1)  # start, stop, step
    MID_RANGE = (1.0, 2.5, 0.1)
    NUM_ROIS = 2
    
    print("=" * 60)
    print("PHASE 1: Uniform ratios across all ROIs")
    print("=" * 60)
    
    results = grid_search(test_images, TOP_RANGE, MID_RANGE, NUM_ROIS)
    
    print()
    print("=" * 60)
    print("TOP 10 CONFIGURATIONS (UNIFORM)")
    print("=" * 60)
    
    for rank, (accuracy, ratios) in enumerate(results[:10], 1):
        print(f"{rank:2d}. Accuracy: {accuracy:5.1f}% | Ratios: {ratios[0]}")
    
    # Save results
    output_path = Path("optimization_results.json")
    with output_path.open("w") as f:
        json.dump({
            "search_type": "uniform",
            "top_range": TOP_RANGE,
            "mid_range": MID_RANGE,
            "num_rois": NUM_ROIS,
            "results": [
                {
                    "accuracy": acc,
                    "ratios": ratios
                }
                for acc, ratios in results[:50]  # Save top 50
            ]
        }, f, indent=2)
    
    print()
    print(f"Results saved to {output_path}")
    
    # Ask if user wants to run independent optimization
    print()
    print("=" * 60)
    print("PHASE 2: Independent ratios per ROI (OPTIONAL)")
    print("=" * 60)
    print(f"This will test {(len(list(np.arange(*TOP_RANGE))) * len(list(np.arange(*MID_RANGE)))) ** NUM_ROIS} combinations")
    print("This may take a very long time. Skip for now? (y/n)")
    
    # For now, skip interactive prompt in automated runs
    skip_independent = True
    
    if not skip_independent:
        # Refine search around best uniform result
        best_accuracy, best_ratios = results[0]
        best_top, best_mid = best_ratios[0]
        
        # Narrow search range
        refined_top_range = (max(1.0, best_top - 0.3), best_top + 0.3, 0.05)
        refined_mid_range = (max(1.0, best_mid - 0.3), best_mid + 0.3, 0.05)
        
        print(f"Refining search around best uniform result: {best_ratios[0]}")
        
        independent_results = independent_grid_search(
            test_images,
            refined_top_range,
            refined_mid_range,
            NUM_ROIS
        )
        
        print()
        print("=" * 60)
        print("TOP 10 CONFIGURATIONS (INDEPENDENT)")
        print("=" * 60)
        
        for rank, (accuracy, ratios) in enumerate(independent_results[:10], 1):
            print(f"{rank:2d}. Accuracy: {accuracy:5.1f}% | Ratios: {ratios}")
        
        # Save independent results
        independent_output = Path("optimization_results_independent.json")
        with independent_output.open("w") as f:
            json.dump({
                "search_type": "independent",
                "top_range": refined_top_range,
                "mid_range": refined_mid_range,
                "num_rois": NUM_ROIS,
                "results": [
                    {
                        "accuracy": acc,
                        "ratios": ratios
                    }
                    for acc, ratios in independent_results[:50]
                ]
            }, f, indent=2)
        
        print(f"Independent results saved to {independent_output}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
