# Visual Overlay System

## Overview

The web dashboard includes a real-time canvas overlay that draws detection boxes on the latest detection image, providing instant visual feedback for box positioning and sizing.

## Visual Elements

### Detection Boxes
- **Border**: 3px solid green (#00ff00)
- **Fill**: Semi-transparent green (rgba(0, 255, 0, 0.15))
- **Purpose**: Shows the exact detection region

### Labels
- **Background**: Green with 80% opacity
- **Text**: Black, bold 14px Arial
- **Content**: 
  - Line 1: Box number (e.g., "Box 1")
  - Line 2: Dimensions in pixels (e.g., "128×96px")
- **Position**: Above the box

### Corner Handles
- **Size**: 8×8px squares
- **Color**: Solid green (#00ff00)
- **Positions**: All four corners (top-left, top-right, bottom-left, bottom-right)
- **Purpose**: Visual reference for box boundaries

### Center Crosshair
- **Style**: 1px green lines
- **Size**: 10px cross
- **Position**: Center of box
- **Purpose**: Precise center reference

## Coordinate System

### Storage Format (web_ui.config.py)
Boxes stored in **pixel coordinates**:
```python
visual_prompts = [
    [x1, y1, x2, y2],  # e.g., [100, 200, 250, 350]
]
```

### Display Scaling
Canvas automatically scales coordinates based on displayed image size:

```javascript
const scaleX = img.offsetWidth / imageDimensions[0];
const scaleY = img.offsetHeight / imageDimensions[1];

const displayX1 = box[0] * scaleX;
const displayY1 = box[1] * scaleY;
```

This ensures boxes appear correctly regardless of:
- Browser window size
- Image zoom level
- Responsive layout changes

## Update Triggers

The overlay redraws automatically when:

1. **Image loads** - `onload="drawDetectionBoxes()"`
2. **Boxes change** - After any position/size adjustment
3. **Window resizes** - `window.addEventListener('resize', drawDetectionBoxes)`
4. **Boxes loaded** - After fetching from API
5. **Manual refresh** - When user clicks refresh button

## Performance

- **Drawing time**: ~5-10ms for typical 2-3 boxes
- **No server calls**: Overlay updates instantly client-side
- **Canvas cleared**: Each redraw clears and redraws all boxes
- **Memory efficient**: Single canvas element reused

## Example Visual Output

```
┌──────────────────────────────────────┐
│  Latest Detection Image              │
│                                      │
│  ┌─────────────────┐                │
│  │ Box 1: 150×120px│                │
│  ├─────────────────┤                │
│  │░░░░░░░░░░░░░░░░░│                │
│  │░░░░░░░┼░░░░░░░░░│  ← Center     │
│  │░░░░░░░░░░░░░░░░░│     crosshair  │
│  └─────────────────┘                │
│  ↑                 ↑                │
│  Corner handles                     │
│                                      │
└──────────────────────────────────────┘
```

## Code Structure

### HTML Structure
```html
<div class="image-container">
    <img id="detection-image" />
    <canvas id="detection-overlay" class="detection-overlay"></canvas>
</div>
```

### CSS Positioning
```css
.image-container {
    position: relative;
    display: inline-block;
}

.detection-overlay {
    position: absolute;
    top: 0;
    left: 0;
    pointer-events: none;  /* Click-through to image */
}
```

### JavaScript Drawing
```javascript
function drawDetectionBoxes() {
    const canvas = document.getElementById('detection-overlay');
    const ctx = canvas.getContext('2d');
    
    // Size canvas to match image
    canvas.width = img.offsetWidth;
    canvas.height = img.offsetHeight;
    
    // Draw each box
    detectionBoxes.forEach((box, index) => {
        // Scale coordinates
        const x1 = box[0] * scaleX;
        const y1 = box[1] * scaleY;
        // ... draw box, label, handles, crosshair
    });
}
```

## User Workflow

1. **View image**: Latest detection screenshot loads
2. **See boxes**: Green overlays show current detection regions
3. **Adjust position**: Click X+/X-/Y+/Y- buttons
4. **See update**: Overlay redraws instantly
5. **Verify**: Visual confirmation before next detection
6. **Refine**: Continue adjusting until perfect

## Benefits

- ✅ **Instant feedback** - No waiting for server response
- ✅ **Accurate positioning** - See exact pixel boundaries
- ✅ **Visual dimensions** - Size displayed on each box
- ✅ **Multiple boxes** - All boxes visible simultaneously
- ✅ **Responsive** - Works on any screen size
- ✅ **Non-intrusive** - Click-through overlay doesn't block interaction

## Accessibility

- Color: High-contrast green (#00ff00) visible on most backgrounds
- Labels: Black text on green background for readability
- Legend: Explains green boxes are detection regions
- Alternative: Coordinates also shown in text form below controls
