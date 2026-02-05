# Diagrams for Article

This folder contains visual diagrams referenced in the article.

## Files

### architecture.svg
**System Architecture Overview**
- Shows the complete flow: Upload → Process → Score
- Three-phase architecture with Lambda functions
- Technology stack at the bottom
- Format: SVG (scalable vector graphics)

### scoring-results.svg
**Sample Scoring Output**
- Real example: John Doe's resume scoring 92/100
- Detailed skill breakdown with evidence quotes
- Shows 5 core skills with years of experience
- Visual representation of scoring dashboard
- Format: SVG (scalable vector graphics)

## Viewing the Diagrams

### In GitHub
The SVG files will render directly in the article when viewed on GitHub.

### Locally
Open the SVG files in any modern web browser (Chrome, Firefox, Safari, Edge).

### Converting to PNG (Optional)

If you need PNG versions for presentations or other uses:

**Using Inkscape (free):**
```bash
inkscape architecture.svg --export-type=png --export-dpi=300 --export-filename=architecture.png
```

**Using ImageMagick:**
```bash
convert -density 300 architecture.svg architecture.png
```

**Online Converters:**
- https://cloudconvert.com/svg-to-png
- https://convertio.co/svg-png/

## Creating More Diagrams

The article references these two diagrams. If you want to create additional diagrams:

1. Use the Figma specifications in `/FIGMA_DIAGRAM_SPECS.md`
2. Create diagrams in Figma following the specs
3. Export as SVG or PNG (2x resolution for retina displays)
4. Place in this folder
5. Reference in the article using relative paths

Example:
```markdown
![Diagram Name](./diagrams/diagram-name.svg)
```

## Diagram Color Palette

Consistent colors used across all diagrams:

- **AWS Orange:** #FF9900
- **Tech Blue:** #232F3E
- **Success Green:** #1B9C85, #4CAF50
- **Accent Purple:** #6B48FF
- **Warning Yellow:** #FFB020
- **Background Gray:** #F5F5F5
- **Border Gray:** #E0E0E0

## Fonts

- **Headings:** Arial Bold (or Inter Bold if available)
- **Body:** Arial Regular (or Inter Regular if available)
- **Numbers:** Arial SemiBold

---

**Note:** SVG files are preferred for web use because they scale perfectly at any size and have smaller file sizes than raster images (PNG/JPG).
