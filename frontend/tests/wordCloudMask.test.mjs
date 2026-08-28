import assert from 'node:assert/strict';
import test from 'node:test';
import {
  binarizePixels,
  getContainRect,
  getLuma,
  getMaskCanvasSize,
  getMaskValidity,
  MAX_MASK_CANVAS_SIDE,
} from '../src/utils/wordCloudMask.ts';
import { buildOpacityFamily } from '../src/utils/wordCloudColors.ts';

function rgba(...values) { return new Uint8ClampedArray(values); }

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
