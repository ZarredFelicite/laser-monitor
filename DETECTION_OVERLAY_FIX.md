# Detection Box Overlay Fix

## Problem
Detection box overlays were not displaying correctly on the dashboard.

## Root Cause
The overlay rendering used configured `imageDimensions` instead of the actual loaded image's natural dimensions. If the actual image dimensions differed from the configured dimensions (1920×1080), the boxes would be drawn in the wrong positions.

## Solution

### 1. Use Natural Image Dimensions
Changed `drawDetectionBoxes()` to use `img.naturalWidth` and `img.naturalHeight` as the source dimensions instead of the configured `imageDimensions`:

```javascript
// Before:
const scaleX = img.offsetWidth / imageDimensions[0];
const scaleY = img.offsetHeight / imageDimensions[1];

// After:
const sourceWidth = img.naturalWidth || imageDimensions[0];
const sourceHeight = img.naturalHeight || imageDimensions[1];
const scaleX = img.offsetWidth / sourceWidth;
const scaleY = img.offsetHeight / sourceHeight;
```

This ensures boxes are positioned correctly regardless of the actual image dimensions.

### 2. Added Debug Logging
Added comprehensive console logging to help diagnose overlay issues:
- Box count and coordinates
- Configured dimensions vs natural image size
- Displayed size and canvas size
- Scale factors
- Individual box positions after scaling

### 3. Improved Image Refresh
Added automatic redraw with delay after image refresh to ensure overlay updates when image changes.

## How It Works

1. **Backend**: Stores boxes in normalized coordinates (0-1) in `web_ui.config.py`
2. **API**: Converts normalized → pixel coordinates when loading
3. **Frontend**: Scales pixel coordinates to match displayed image size using natural dimensions
4. **Rendering**: Draws boxes on canvas overlay positioned over image

## Testing
With the example config (2 small indicator boxes):
- Box 1: 19×65px at position (1440, 443) on 1920×1080 image
- Box 2: 19×22px at position (346, 497) on 1920×1080 image

When displayed at 50% size (960×540):
- Box 1: 9.6×32.4px at (720, 221)
- Box 2: 9.6×10.8px at (173, 248)

