# Assets Directory

This directory contains static assets used in the project documentation.

## Structure

```
docs/assets/
├── images/          # Architecture diagrams, screenshots, GIFs, demo videos
├── diagrams/        # Source files for diagrams (e.g., .drawio, .lucid)
└── README.md        # This file
```

## Usage Guidelines

### Adding Images

1. **Place images in the appropriate subdirectory:**
   - Architecture diagrams → `images/`
   - Screenshots → `images/`
   - GIFs/videos → `images/`

2. **Naming conventions:**
   - Use lowercase with hyphens: `architecture-overview.png`
   - Be descriptive: `deployment-workflow.gif` not `image1.gif`
   - Include version if needed: `architecture-v2.png`

3. **Recommended formats:**
   - PNG for diagrams and screenshots (better quality)
   - JPG for photos (smaller size)
   - GIF for short animations
   - SVG for vector graphics (scalable)

### Referencing in README

From the root README.md, reference images using relative paths:

```markdown
![Architecture Overview](docs/assets/images/architecture-overview.png)
```

Or for clickable images:

```markdown
[![Demo Video](docs/assets/images/demo-thumbnail.gif)](https://youtu.be/your-video-link)
```

### Image Optimization

- Keep images under 1-2 MB when possible
- Use tools like TinyPNG or ImageOptim to compress
- Consider hosting large videos externally (YouTube, Vimeo)

## Examples

See the main [README.md](../../README.md) for examples of how these assets are used.
