import { useCallback, useEffect, useRef, useState } from 'react';
import {
  createWordCloudMask,
  getMaskValidity,
  MAX_MASK_FILE_SIZE,
  MAX_SOURCE_IMAGE_SIDE,
  type ImageSize,
} from '../utils/wordCloudMask';

type DecodedImage = ImageBitmap | HTMLImageElement;
type ProcessingStatus = 'idle' | 'decoding' | 'processing';

interface LoadedImage {
  image: DecodedImage;
  size: ImageSize;
  objectUrl: string;
}

const SUPPORTED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const MASK_UPDATE_DEBOUNCE_MS = 350;

function closeImage(image: DecodedImage | null) {
  if (image && 'close' in image && typeof image.close === 'function') image.close();
}

function decodeWithImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('图片无法解码，请更换一张 JPG、PNG 或 WebP 图片。'));
    image.src = url;
  });
}

async function decodeFile(file: File, objectUrl: string): Promise<DecodedImage> {
  if ('createImageBitmap' in window) {
    try {
      return await createImageBitmap(file);
    } catch {
      // Older WebViews can reject a format even when <img> can display it.
    }
  }
  return decodeWithImage(objectUrl);
}

export function useWordCloudMask(targetSize: ImageSize | null) {
  const [threshold, setThreshold] = useState(128);
  const [inverted, setInverted] = useState(false);
  const [sourcePreviewUrl, setSourcePreviewUrl] = useState<string | null>(null);
  const [sourceSize, setSourceSize] = useState<ImageSize | null>(null);
  const [maskPreviewUrl, setMaskPreviewUrl] = useState<string | null>(null);
  const [appliedMask, setAppliedMask] = useState<HTMLCanvasElement | null>(null);
  const [drawableRatio, setDrawableRatio] = useState<number | null>(null);
  const [status, setStatus] = useState<ProcessingStatus>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const loadedRef = useRef<LoadedImage | null>(null);
  const appliedMaskRef = useRef<HTMLCanvasElement | null>(null);
  const requestIdRef = useRef(0);
  const [revision, setRevision] = useState(0);
  const [appliedVersion, setAppliedVersion] = useState(0);

  const releaseLoadedImage = useCallback(() => {
    const loaded = loadedRef.current;
    if (!loaded) return;
    closeImage(loaded.image);
    URL.revokeObjectURL(loaded.objectUrl);
    loadedRef.current = null;
  }, []);

  const removeMask = useCallback(() => {
    requestIdRef.current += 1;
    releaseLoadedImage();
    setSourcePreviewUrl(null);
    setSourceSize(null);
    setMaskPreviewUrl(null);
    setAppliedMask(null);
    appliedMaskRef.current = null;
    setAppliedVersion(0);
    setDrawableRatio(null);
    setMessage(null);
    setStatus('idle');
  }, [releaseLoadedImage]);

  const resetMask = useCallback(() => {
    removeMask();
    setThreshold(128);
    setInverted(false);
  }, [removeMask]);

  const selectFile = useCallback(async (file: File) => {
    const requestId = ++requestIdRef.current;
    if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
      setMessage('仅支持 JPG、PNG 或 WebP 图片。');
      setStatus('idle');
      return null;
    }
    if (file.size > MAX_MASK_FILE_SIZE) {
      setMessage('图片不能超过 10 MB。');
      setStatus('idle');
      return null;
    }

    const objectUrl = URL.createObjectURL(file);
    setStatus('decoding');
    setMessage(null);

    try {
      const image = await decodeFile(file, objectUrl);
      const size = { width: image.width, height: image.height };
      if (size.width > MAX_SOURCE_IMAGE_SIDE || size.height > MAX_SOURCE_IMAGE_SIDE) {
        closeImage(image);
        URL.revokeObjectURL(objectUrl);
        throw new Error('图片单边不能超过 8192 像素。');
      }
      if (!size.width || !size.height) {
        closeImage(image);
        URL.revokeObjectURL(objectUrl);
        throw new Error('图片尺寸无效，请更换一张图片。');
      }
      if (requestId !== requestIdRef.current) {
        closeImage(image);
        URL.revokeObjectURL(objectUrl);
        return false;
      }

      releaseLoadedImage();
      loadedRef.current = { image, size, objectUrl };
      setSourcePreviewUrl(objectUrl);
      setSourceSize(size);
      setMaskPreviewUrl(null);
      setDrawableRatio(null);
      setRevision(value => value + 1);
      return requestId;
    } catch (error) {
      URL.revokeObjectURL(objectUrl);
      if (requestId === requestIdRef.current) {
        setMessage(error instanceof Error ? error.message : '图片处理失败，请更换一张图片。');
        setStatus('idle');
      }
      return null;
    }
  }, [releaseLoadedImage]);

  useEffect(() => {
    const loaded = loadedRef.current;
    if (!loaded) return;
    const requestId = requestIdRef.current;
    setStatus('processing');

    const timer = window.setTimeout(() => {
      try {
        const processed = createWordCloudMask(loaded.image, loaded.size, threshold, inverted, targetSize ?? undefined);
        if (requestId !== requestIdRef.current) return;

        setMaskPreviewUrl(processed.canvas.toDataURL('image/png'));
        setDrawableRatio(processed.drawableRatio);
        const validity = getMaskValidity(processed.drawableRatio);
        if (validity === 'valid') {
          setAppliedMask(processed.canvas);
          appliedMaskRef.current = processed.canvas;
          setAppliedVersion(requestId);
          setMessage(null);
        } else if (validity === 'too-small') {
          setMessage(appliedMaskRef.current ? '可生成区域过小，请调整阈值或反转词语区域；已保留上一次有效轮廓。' : '可生成区域过小，请调整阈值或反转词语区域。');
        } else {
          setMessage(appliedMaskRef.current ? '轮廓区分度较低，请调整阈值或反转词语区域；已保留上一次有效轮廓。' : '轮廓区分度较低，请调整阈值或反转词语区域。');
        }
      } catch (error) {
        if (requestId === requestIdRef.current) {
          setMessage(error instanceof Error ? error.message : '图片处理失败，请更换一张图片。');
        }
      } finally {
        if (requestId === requestIdRef.current) setStatus('idle');
      }
    }, MASK_UPDATE_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [inverted, revision, targetSize, threshold]);

  useEffect(() => () => {
    requestIdRef.current += 1;
    releaseLoadedImage();
  }, [releaseLoadedImage]);

  return {
    threshold,
    setThreshold,
    inverted,
    setInverted,
    sourcePreviewUrl,
    sourceSize,
    maskPreviewUrl,
    appliedMask,
    drawableRatio,
    status,
    message,
    selectFile,
    removeMask,
    resetMask,
    appliedVersion,
    canEnableMask: appliedMask !== null,
  };
}
