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

function matchesBytes(bytes: Uint8Array, offset: number, expected: readonly number[]): boolean {
  return expected.every((value, index) => bytes[offset + index] === value);
}

function matchesAscii(bytes: Uint8Array, offset: number, expected: string): boolean {
  if (offset < 0 || offset + expected.length > bytes.length) return false;
  for (let index = 0; index < expected.length; index += 1) {
    if (bytes[offset + index] !== expected.charCodeAt(index)) return false;
  }
  return true;
}

function readUint16BigEndian(bytes: Uint8Array, offset: number): number {
  return bytes[offset] * 0x100 + bytes[offset + 1];
}

function readUint16LittleEndian(bytes: Uint8Array, offset: number): number {
  return bytes[offset] + bytes[offset + 1] * 0x100;
}

function readUint24LittleEndian(bytes: Uint8Array, offset: number): number {
  return bytes[offset] + bytes[offset + 1] * 0x100 + bytes[offset + 2] * 0x10000;
}

function readUint32BigEndian(bytes: Uint8Array, offset: number): number {
  return bytes[offset] * 0x1000000
    + bytes[offset + 1] * 0x10000
    + bytes[offset + 2] * 0x100
    + bytes[offset + 3];
}

function readUint32LittleEndian(bytes: Uint8Array, offset: number): number {
  return bytes[offset]
    + bytes[offset + 1] * 0x100
    + bytes[offset + 2] * 0x10000
    + bytes[offset + 3] * 0x1000000;
}

function checkedImageSize(width: number, height: number): ImageSize {
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0) {
    throw new Error('图片尺寸无效，请更换一张图片。');
  }
  return { width, height };
}

function getPngMetadataSize(bytes: Uint8Array): ImageSize {
  const signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a] as const;
  if (bytes.length < 24
    || !matchesBytes(bytes, 0, signature)
    || !matchesAscii(bytes, 12, 'IHDR')
    || readUint32BigEndian(bytes, 8) !== 13) {
    throw new Error('PNG 文件头无效，无法读取图片尺寸。');
  }
  return checkedImageSize(readUint32BigEndian(bytes, 16), readUint32BigEndian(bytes, 20));
}

const JPEG_START_OF_FRAME_MARKERS = new Set([
  0xc0, 0xc1, 0xc2, 0xc3,
  0xc5, 0xc6, 0xc7,
  0xc9, 0xca, 0xcb,
  0xcd, 0xce, 0xcf,
]);

function getJpegMetadataSize(bytes: Uint8Array): ImageSize {
  if (bytes.length < 4 || !matchesBytes(bytes, 0, [0xff, 0xd8])) {
    throw new Error('JPEG 文件头无效，无法读取图片尺寸。');
  }

  let offset = 2;
  while (offset < bytes.length) {
    if (bytes[offset] !== 0xff) {
      throw new Error('JPEG 文件结构无效，无法读取图片尺寸。');
    }
    while (offset < bytes.length && bytes[offset] === 0xff) offset += 1;
    if (offset >= bytes.length) break;

    const marker = bytes[offset];
    offset += 1;
    if (marker === 0xd9 || marker === 0xda) break;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd8)) continue;
    if (offset + 2 > bytes.length) break;

    const segmentLength = readUint16BigEndian(bytes, offset);
    if (segmentLength < 2 || offset + segmentLength > bytes.length) {
      throw new Error('JPEG 文件结构无效，无法读取图片尺寸。');
    }
    if (JPEG_START_OF_FRAME_MARKERS.has(marker)) {
      if (segmentLength < 7) throw new Error('JPEG 尺寸信息无效。');
      return checkedImageSize(
        readUint16BigEndian(bytes, offset + 5),
        readUint16BigEndian(bytes, offset + 3),
      );
    }
    offset += segmentLength;
  }

  throw new Error('JPEG 中未找到图片尺寸信息。');
}

function getWebpMetadataSize(bytes: Uint8Array): ImageSize {
  if (bytes.length < 20 || !matchesAscii(bytes, 0, 'RIFF') || !matchesAscii(bytes, 8, 'WEBP')) {
    throw new Error('WebP 文件头无效，无法读取图片尺寸。');
  }

  const declaredEnd = readUint32LittleEndian(bytes, 4) + 8;
  if (declaredEnd < 20 || declaredEnd > bytes.length) {
    throw new Error('WebP 文件结构无效，无法读取图片尺寸。');
  }

  let offset = 12;
  while (offset + 8 <= declaredEnd) {
    const chunkSize = readUint32LittleEndian(bytes, offset + 4);
    const payloadOffset = offset + 8;
    const chunkEnd = payloadOffset + chunkSize;
    if (chunkEnd > declaredEnd) throw new Error('WebP 文件结构无效，无法读取图片尺寸。');

    if (matchesAscii(bytes, offset, 'VP8X')) {
      if (chunkSize < 10) throw new Error('WebP 尺寸信息无效。');
      return checkedImageSize(
        readUint24LittleEndian(bytes, payloadOffset + 4) + 1,
        readUint24LittleEndian(bytes, payloadOffset + 7) + 1,
      );
    }
    if (matchesAscii(bytes, offset, 'VP8L')) {
      if (chunkSize < 5 || bytes[payloadOffset] !== 0x2f) throw new Error('WebP 尺寸信息无效。');
      return checkedImageSize(
        1 + bytes[payloadOffset + 1] + ((bytes[payloadOffset + 2] & 0x3f) << 8),
        1 + (bytes[payloadOffset + 2] >>> 6)
          + (bytes[payloadOffset + 3] << 2)
          + ((bytes[payloadOffset + 4] & 0x0f) << 10),
      );
    }
    if (matchesAscii(bytes, offset, 'VP8 ')) {
      if (chunkSize < 10 || !matchesBytes(bytes, payloadOffset + 3, [0x9d, 0x01, 0x2a])) {
        throw new Error('WebP 尺寸信息无效。');
      }
      return checkedImageSize(
        readUint16LittleEndian(bytes, payloadOffset + 6) & 0x3fff,
        readUint16LittleEndian(bytes, payloadOffset + 8) & 0x3fff,
      );
    }

    offset = chunkEnd + (chunkSize % 2);
  }

  throw new Error('WebP 中未找到图片尺寸信息。');
}

/** Reads dimensions from the file container without invoking an image decoder. */
export function getImageMetadataSize(bytes: Uint8Array, mimeType: string): ImageSize {
  if (mimeType === 'image/png') return getPngMetadataSize(bytes);
  if (mimeType === 'image/jpeg') return getJpegMetadataSize(bytes);
  if (mimeType === 'image/webp') return getWebpMetadataSize(bytes);
  throw new Error('仅支持 JPG、PNG 或 WebP 图片。');
}

export function isSourceImageSizeAllowed(size: ImageSize): boolean {
  return Number.isSafeInteger(size.width)
    && Number.isSafeInteger(size.height)
    && size.width > 0
    && size.height > 0
    && size.width <= MAX_SOURCE_IMAGE_SIDE
    && size.height <= MAX_SOURCE_IMAGE_SIDE;
}

export function areImageSizesCompatible(metadataSize: ImageSize, decodedSize: ImageSize): boolean {
  return (metadataSize.width === decodedSize.width && metadataSize.height === decodedSize.height)
    || (metadataSize.width === decodedSize.height && metadataSize.height === decodedSize.width);
}

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
