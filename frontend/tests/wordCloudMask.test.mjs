import assert from 'node:assert/strict';
import test from 'node:test';
import {
  areImageSizesCompatible,
  binarizePixels,
  getContainRect,
  getImageMetadataSize,
  getLuma,
  getMaskCanvasSize,
  getMaskValidity,
  isSourceImageSizeAllowed,
  MAX_MASK_CANVAS_SIDE,
  MAX_SOURCE_IMAGE_SIDE,
} from '../src/utils/wordCloudMask.ts';
import { buildOpacityFamily } from '../src/utils/wordCloudColors.ts';

function rgba(...values) { return new Uint8ClampedArray(values); }

function pngHeader(width, height) {
  const bytes = new Uint8Array(24);
  bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], 0);
  bytes.set([0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52], 8);
  new DataView(bytes.buffer).setUint32(16, width);
  new DataView(bytes.buffer).setUint32(20, height);
  return bytes;
}

function jpegHeader(width, height) {
  return new Uint8Array([
    0xff, 0xd8,
    0xff, 0xe0, 0x00, 0x04, 0x00, 0x00,
    0xff, 0xc2, 0x00, 0x07, 0x08,
    (height >>> 8) & 0xff, height & 0xff,
    (width >>> 8) & 0xff, width & 0xff,
  ]);
}

function webpVp8xHeader(width, height) {
  const bytes = new Uint8Array(30);
  bytes.set([0x52, 0x49, 0x46, 0x46], 0); // RIFF
  new DataView(bytes.buffer).setUint32(4, bytes.length - 8, true);
  bytes.set([0x57, 0x45, 0x42, 0x50, 0x56, 0x50, 0x38, 0x58], 8); // WEBP + VP8X
  new DataView(bytes.buffer).setUint32(16, 10, true);
  const widthMinusOne = width - 1;
  const heightMinusOne = height - 1;
  bytes.set([
    widthMinusOne & 0xff, (widthMinusOne >>> 8) & 0xff, (widthMinusOne >>> 16) & 0xff,
    heightMinusOne & 0xff, (heightMinusOne >>> 8) & 0xff, (heightMinusOne >>> 16) & 0xff,
  ], 24);
  return bytes;
}

test('解码前从 PNG、JPEG 与 WebP 文件元数据读取尺寸', () => {
  assert.deepEqual(getImageMetadataSize(pngHeader(640, 360), 'image/png'), { width: 640, height: 360 });
  assert.deepEqual(getImageMetadataSize(jpegHeader(1080, 1920), 'image/jpeg'), { width: 1080, height: 1920 });
  assert.deepEqual(getImageMetadataSize(webpVp8xHeader(300, 200), 'image/webp'), { width: 300, height: 200 });
});

test('源图最长边 8192 可接受，8193 在解码前拒绝', () => {
  const boundary = getImageMetadataSize(pngHeader(MAX_SOURCE_IMAGE_SIDE, 1), 'image/png');
  const oversized = getImageMetadataSize(webpVp8xHeader(1, MAX_SOURCE_IMAGE_SIDE + 1), 'image/webp');
  assert.equal(isSourceImageSizeAllowed(boundary), true);
  assert.equal(isSourceImageSizeAllowed(oversized), false);
});

test('元数据尺寸与解码尺寸允许完全一致或 EXIF 旋转后的宽高互换', () => {
  assert.equal(areImageSizesCompatible({ width: 2, height: 3 }, { width: 2, height: 3 }), true);
  assert.equal(areImageSizesCompatible({ width: 2, height: 3 }, { width: 3, height: 2 }), true);
  assert.equal(areImageSizesCompatible({ width: 2, height: 3 }, { width: 3, height: 4 }), false);
});

test('亮度计算采用标准 RGB 加权', () => {
  assert.equal(getLuma(0, 0, 0), 0);
  assert.equal(getLuma(255, 255, 255), 255);
  assert.equal(Math.round(getLuma(255, 0, 0)), 76);
});

test('contain 缩放完整保留横竖图片并居中', () => {
  assert.deepEqual(getContainRect({ width: 400, height: 200 }, { width: 100, height: 100 }), {
    x: 0, y: 25, width: 100, height: 50,
  });
  assert.deepEqual(getContainRect({ width: 200, height: 400 }, { width: 100, height: 100 }), {
    x: 25, y: 0, width: 50, height: 100,
  });
});

test('工作 Canvas 限制最长边并防护零尺寸', () => {
  assert.deepEqual(getMaskCanvasSize({ width: 3000, height: 2000 }), {
    width: MAX_MASK_CANVAS_SIDE, height: MAX_MASK_CANVAS_SIDE,
  });
  assert.deepEqual(getMaskCanvasSize({ width: 0, height: 100 }), { width: 0, height: 0 });
  assert.deepEqual(getMaskCanvasSize(
    { width: 3000, height: 2000 },
    { width: 1600, height: 600 },
  ), { width: 1024, height: 384 });
  assert.deepEqual(getMaskCanvasSize(
    { width: 3000, height: 2000 },
    { width: 640, height: 300 },
  ), { width: 640, height: 300 });
});

test('二值化覆盖阈值、反转、透明背景且不修改源像素', () => {
  const source = rgba(
    0, 0, 0, 255,       // black
    128, 128, 128, 255, // middle gray
    255, 255, 255, 255, // white
    0, 0, 0, 0,         // transparent is white background
  );
  const original = new Uint8ClampedArray(source);
  const atZero = binarizePixels(source, 0, false);
  assert.deepEqual([...atZero.pixels], [0, 0, 0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255]);
  assert.equal(atZero.drawableRatio, .25);
  assert.deepEqual(source, original);

  const at128 = binarizePixels(source, 128, false);
  assert.equal(at128.drawableRatio, .5);
  const at255 = binarizePixels(source, 255, false);
  assert.equal(at255.drawableRatio, .75);
  const inverted = binarizePixels(source, 128, true);
  assert.equal(inverted.drawableRatio, .5);
  assert.deepEqual([...inverted.pixels.slice(0, 4)], [255, 255, 255, 255]);
  assert.deepEqual([...inverted.pixels.slice(12, 16)], [0, 0, 0, 255]);
});

test('可绘制区域按 5% 与 95% 门限给出提示状态', () => {
  assert.equal(getMaskValidity(0.049), 'too-small');
  assert.equal(getMaskValidity(0.05), 'valid');
  assert.equal(getMaskValidity(0.95), 'valid');
  assert.equal(getMaskValidity(0.951), 'too-large');
});

test('家族多色从基色生成递增透明度色阶', () => {
  assert.deepEqual(buildOpacityFamily('#FB7299', 0.3, 3), [
    'rgba(251, 114, 153, 0.30)',
    'rgba(251, 114, 153, 0.65)',
    'rgba(251, 114, 153, 1.00)',
  ]);
  assert.deepEqual(buildOpacityFamily('invalid', 0.3), []);
});
