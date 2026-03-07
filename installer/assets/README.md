# UI Assets

This directory should contain the following image files for the installer:

## Required Files

1. **app-icon.ico** - Application icon
   - Recommended size: 256x256 pixels
   - Format: ICO with multiple sizes (16, 32, 48, 256)
   - Used for: Desktop shortcut, start menu, uninstaller

2. **wizard-side.bmp** - Setup wizard sidebar image
   - Size: 164x314 pixels
   - Format: 24-bit BMP
   - Used for: Left side of installation wizard

3. **wizard-small.bmp** - Setup wizard small icon
   - Size: 55x55 pixels
   - Format: 24-bit BMP
   - Used for: Top-right corner of wizard windows

## Creating These Assets

### Quick Method

1. Find or create a bird/feather logo (SVG preferred)
2. Convert to required formats using:
   - Online: [ICO Convert](https://www.icoconverter.com/)
   - Online: [BMP Convert](https://convertio.co/bmp/)
   - Local: GIMP, Paint.NET, or Photoshop

### Design Guidelines

- Use a simple bird or feather icon
- Primary color: #667eea (purple gradient)
- Keep it recognizable at small sizes
- Avoid text in icons (not readable at 16x16)

### Placeholder

If these files don't exist, Inno Setup will use default images.
The installer will still work correctly.

## Example Icon

You can use the WingScribe logo if available:
- WingScribe logo should be converted to ICO format
- Use a bird silhouette or feather design
- Consider using a stylized "WS" monogram
