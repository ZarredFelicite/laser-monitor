#!/usr/bin/env python3
"""
Visual Prompt Selector - Interactive bounding box selection tool

Usage: python visual_prompt_selector.py <image_path> [output_config.py]

Mouse controls:
- Click and drag to create bounding boxes
- Right-click on a box to delete it

Keyboard controls:
- 's' or ENTER: Save configuration and exit
- 'r': Reset (clear all boxes)
- 'd': Delete last box
- 'q' or ESC: Quit without saving
- 'h': Show help

Output: Python config file with refer_image path and visual_prompts bounding boxes
"""

import cv2
import json
import sys
import os
from pathlib import Path
import argparse


class VisualPromptSelector:
    def __init__(self, image_path, output_path=None):
        self.image_path = Path(image_path)
        self.output_path = output_path or self.image_path.with_suffix('.config.py')
        
        # Load image
        loaded_image = cv2.imread(str(self.image_path))
        if loaded_image is None:
            raise ValueError(f"Could not load image: {self.image_path}")
        
        # Resize to 1920x1080
        self.original_image = cv2.resize(loaded_image, (1920, 1080))
        
        self.image = self.original_image.copy()
        self.height, self.width = self.image.shape[:2]
        
        # State
        self.bboxes = []  # List of (x1, y1, x2, y2) tuples
        self.current_box = None  # Currently being drawn box
        self.drawing = False
        self.start_point = None
        
        # Colors
        self.box_color = (0, 255, 0)  # Green
        self.current_color = (0, 255, 255)  # Yellow
        self.text_color = (255, 255, 255)  # White
        self.bg_color = (0, 0, 0)  # Black background for text
        
        # Window setup
        self.window_name = "Visual Prompt Selector"
        cv2.namedWindow(self.window_name, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)
        
    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.start_point = (x, y)
            self.current_box = None
            
        elif event == cv2.EVENT_MOUSEMOVE:
            if self.drawing and self.start_point:
                self.current_box = (*self.start_point, x, y)
                
        elif event == cv2.EVENT_LBUTTONUP:
            if self.drawing and self.start_point:
                end_point = (x, y)
                # Normalize coordinates (ensure x1 < x2, y1 < y2)
                x1, y1 = self.start_point
                x2, y2 = end_point
                
                bbox = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
                
                # Only add if box has area
                if bbox[2] - bbox[0] > 5 and bbox[3] - bbox[1] > 5:
                    self.bboxes.append(bbox)
                
                self.drawing = False
                self.current_box = None
                self.start_point = None
                
        elif event == cv2.EVENT_RBUTTONDOWN:
            # Right click to delete box
            self.delete_box_at_point(x, y)
    
    def delete_box_at_point(self, x, y):
        """Delete bounding box that contains the clicked point"""
        for i, (x1, y1, x2, y2) in enumerate(self.bboxes):
            if x1 <= x <= x2 and y1 <= y <= y2:
                del self.bboxes[i]
                break
    
    def draw_text_with_background(self, img, text, pos, font_scale=0.6, thickness=1):
        """Draw text with black background for better visibility"""
        font = cv2.FONT_HERSHEY_SIMPLEX
        (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
        
        x, y = pos
        # Draw background rectangle
        cv2.rectangle(img, (x, y - text_height - baseline), 
                     (x + text_width, y + baseline), self.bg_color, -1)
        # Draw text
        cv2.putText(img, text, pos, font, font_scale, self.text_color, thickness)
    
    def draw_interface(self):
        """Draw the current state of boxes and interface"""
        self.image = self.original_image.copy()
        
        # Draw saved bounding boxes
        for i, (x1, y1, x2, y2) in enumerate(self.bboxes):
            cv2.rectangle(self.image, (x1, y1), (x2, y2), self.box_color, 2)
            # Label each box
            self.draw_text_with_background(self.image, f"Box {i+1}", (x1, y1 - 5))
        
        # Draw current box being drawn
        if self.current_box:
            x1, y1, x2, y2 = self.current_box
            cv2.rectangle(self.image, (x1, y1), (x2, y2), self.current_color, 2)
        
        # Draw help text
        help_lines = [
            f"Boxes: {len(self.bboxes)}",
            "Click+drag: new box",
            "Right-click: delete box",
            "s/ENTER: save | r: reset",
            "d: delete last | q/ESC: quit",
            "h: help"
        ]
        
        for i, line in enumerate(help_lines):
            y_pos = 25 + i * 20
            self.draw_text_with_background(self.image, line, (10, y_pos))
    
    def show_help(self):
        """Display detailed help"""
        help_text = [
            "VISUAL PROMPT SELECTOR HELP",
            "",
            "Mouse Controls:",
            "  Left click + drag: Create new bounding box",
            "  Right click on box: Delete that box",
            "",
            "Keyboard Controls:",
            "  s or ENTER: Save configuration and exit",
            "  r: Reset (clear all boxes)",
            "  d: Delete last box",
            "  q or ESC: Quit without saving",
            "  h: Show this help",
            "",
            "Tips:",
            "  - Create multiple boxes for different visual prompts",
            "  - Boxes are saved as normalized coordinates",
            "  - Output config can be used directly with laser monitor",
            "",
            "Press any key to continue..."
        ]
        
        # Create help image
        help_img = np.zeros((600, 800, 3), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        
        for i, line in enumerate(help_text):
            y_pos = 30 + i * 25
            if line.startswith("VISUAL PROMPT"):
                cv2.putText(help_img, line, (50, y_pos), font, 0.8, (0, 255, 255), 2)
            elif line.endswith(":"):
                cv2.putText(help_img, line, (50, y_pos), font, 0.6, (0, 255, 0), 1)
            else:
                cv2.putText(help_img, line, (70, y_pos), font, 0.5, (255, 255, 255), 1)
        
        cv2.imshow("Help", help_img)
        cv2.waitKey(0)
        cv2.destroyWindow("Help")
    
    def save_config(self):
        """Save configuration to Python file"""
        # Convert bboxes to normalized coordinates
        normalized_bboxes = []
        for x1, y1, x2, y2 in self.bboxes:
            normalized_bboxes.append([
                x1 / self.width,
                y1 / self.height, 
                x2 / self.width,
                y2 / self.height
            ])
        
        # Generate Python config file
        config_content = f'''#!/usr/bin/env python3
"""
Visual Prompts Configuration
Generated by visual_prompt_selector.py

Usage:
    from config.config import default_config, create_config_with_visual_prompts
    config = create_config_with_visual_prompts(default_config, "{self.output_path}")
"""

# Reference image path
refer_image = r"{str(self.image_path.absolute())}"

# Visual prompt bounding boxes (normalized coordinates: x1, y1, x2, y2)
visual_prompts = {normalized_bboxes!r}

# Image dimensions (for reference)
image_dimensions = {{
    "width": {self.width},
    "height": {self.height}
}}

# Metadata
metadata = {{
    "created_with": "visual_prompt_selector.py",
    "num_prompts": {len(normalized_bboxes)},
    "original_image": r"{str(self.image_path.absolute())}"
}}
'''
        
        with open(self.output_path, 'w') as f:
            f.write(config_content)
        
        print(f"Python configuration saved to: {self.output_path}")
        print(f"Created {len(self.bboxes)} visual prompt(s)")
        print(f"\nTo use this config:")
        print(f"  from config.config import default_config, create_config_with_visual_prompts")
        print(f"  config = create_config_with_visual_prompts(default_config, '{self.output_path}')")
        return True
    
    def run(self):
        """Main interaction loop"""
        print(f"Visual Prompt Selector")
        print(f"Image: {self.image_path}")
        print(f"Output: {self.output_path}")
        print(f"Image size: {self.width}x{self.height}")
        print("\nControls: Click+drag to create boxes, 's' to save, 'h' for help, 'q' to quit")
        
        while True:
            self.draw_interface()
            cv2.imshow(self.window_name, self.image)
            
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('s') or key == 13:  # 's' or ENTER
                if self.bboxes:
                    if self.save_config():
                        break
                else:
                    print("No bounding boxes to save!")
                    
            elif key == ord('r'):  # Reset
                self.bboxes = []
                print("Reset - all boxes cleared")
                
            elif key == ord('d'):  # Delete last
                if self.bboxes:
                    self.bboxes.pop()
                    print(f"Deleted last box. {len(self.bboxes)} remaining")
                    
            elif key == ord('h'):  # Help
                self.show_help()
                
            elif key == ord('q') or key == 27:  # 'q' or ESC
                print("Quit without saving")
                break
        
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="Interactive visual prompt bounding box selector")
    parser.add_argument("image", help="Path to input image")
    parser.add_argument("-o", "--output", help="Output config file path (default: <image>.config.py)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image):
        print(f"Error: Image file not found: {args.image}")
        sys.exit(1)
    
    try:
        import numpy as np
        selector = VisualPromptSelector(args.image, args.output)
        selector.run()
    except ImportError:
        print("Error: Required packages not found. Install with:")
        print("pip install opencv-python numpy")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()