export const MAX_MASK_FILE_SIZE = 10 * 1024 * 1024;
export const MAX_SOURCE_IMAGE_SIDE = 8192;
export const MAX_MASK_CANVAS_SIDE = 1024;

export interface ImageSize {
  width: number;
  height: number;
}

export interface ContainRect extends ImageSize {
  x: number;
  y: number;
}

export interface ProcessedMask {
  canvas: HTMLCanvasElement;
  drawableRatio: number;
}

export interface BinarizedPixels {
  pixels: Uint8ClampedArray;
  drawableRatio: number;
}

export type MaskValidity = 'valid' | 'too-small' | 'too-large';

export function getLuma(red: number, green: number, blue: number): number {
  return 0.299 * red + 0.587 * green + 0.114 * blue;
}

export function getContainRect(source: ImageSize, target: ImageSize): ContainRect {
  if (source.width <= 0 || source.height <= 0 || target.width <= 0 || target.height <= 0) {
    return { x: 0, y: 0, width: 0, height: 0 };
  }

  const scale = Math.min(target.width / source.width, target.height / source.height);
  const width = Math.max(1, Math.round(source.width * scale));
  const height = Math.max(1, Math.round(source.height * scale));
  return {
    x: Math.floor((target.width - width) / 2),
    y: Math.floor((target.height - height) / 2),
    width,
    height,
  };
}

export function getMaskCanvasSize(source: ImageSize, target?: ImageSize): ImageSize {
  if (source.width <= 0 || source.height <= 0) return { width: 0, height: 0 };
  if (target && target.width > 0 && target.height > 0) {
    const scale = Math.min(1, MAX_MASK_CANVAS_SIDE / Math.max(target.width, target.height));
    return {
      width: Math.max(1, Math.round(target.width * scale)),
      height: Math.max(1, Math.round(target.height * scale)),
    };
  }
  const largestSide = Math.max(source.width, source.height);

  // A square working area lets contain mode keep a portrait or landscape image intact.
  const side = Math.min(MAX_MASK_CANVAS_SIDE, Math.max(1, Math.round(largestSide)));
  return { width: side, height: side };
}

export function getMaskValidity(drawableRatio: number): MaskValidity {
  if (drawableRatio < 0.05) return 'too-small';
  if (drawableRatio > 0.95) return 'too-large';
  return 'valid';
}

/** Converts RGBA pixels without mutating the source buffer. Black means drawable. */
export function binarizePixels(source: Uint8ClampedArray, threshold: number, inverted: boolean): BinarizedPixels {
  if (source.length === 0 || source.length % 4 !== 0) return { pixels: new Uint8ClampedArray(), drawableRatio: 0 };

  const pixels = new Uint8ClampedArray(source.length);
  const safeThreshold = Math.max(0, Math.min(255, Math.round(threshold)));
  let drawablePixels = 0;
  for (let index = 0; index < source.length; index += 4) {
    // A transparent pixel is treated as white background before thresholding.
    const isDark = source[index + 3] >= 128 && getLuma(source[index], source[index + 1], source[index + 2]) <= safeThreshold;
    const drawable = inverted ? !isDark : isDark;
    const value = drawable ? 0 : 255;
    pixels[index] = value;
    pixels[index + 1] = value;
    pixels[index + 2] = value;
    pixels[index + 3] = 255;
    if (drawable) drawablePixels += 1;
  }
  return { pixels, drawableRatio: drawablePixels / (source.length / 4) };
}

/**
 * Converts an in-memory browser image into the black/white convention used by
 * echarts-wordcloud: black pixels are drawable and white pixels are excluded.
 */
export function createWordCloudMask(
  image: CanvasImageSource,
  sourceSize: ImageSize,
  threshold: number,
  inverted: boolean,
  targetSize?: ImageSize,
): ProcessedMask {
  const canvasSize = getMaskCanvasSize(sourceSize, targetSize);
  if (!canvasSize.width || !canvasSize.height) throw new Error('图片尺寸无效');

  const canvas = document.createElement('canvas');
  canvas.width = canvasSize.width;
  canvas.height = canvasSize.height;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) throw new Error('当前环境不支持 Canvas 图片处理');

  // Keep source alpha through drawImage. binarizePixels turns transparent pixels into white.
  const rect = getContainRect(sourceSize, canvasSize);
  context.drawImage(image, rect.x, rect.y, rect.width, rect.height);

  const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
  const binarized = binarizePixels(imageData.data, threshold, inverted);
  imageData.data.set(binarized.pixels);
  context.putImageData(imageData, 0, 0);
  return { canvas, drawableRatio: binarized.drawableRatio };
}
