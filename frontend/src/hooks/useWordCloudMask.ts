import { useCallback, useEffect, useRef, useState } from 'react';
import {
  areImageSizesCompatible,
  createWordCloudMask,
  getImageMetadataSize,
  getMaskValidity,
  isSourceImageSizeAllowed,
  MAX_MASK_FILE_SIZE,
  type ImageSize,
} from '../utils/wordCloudMask';

type DecodedImage = ImageBitmap | HTMLImageElement;
type ProcessingStatus = 'idle' | 'decoding' | 'processing';

interface LoadedImage {
  image: DecodedImage;
  size: ImageSize;
  objectUrl: string;
}

interface PendingCandidate {
  id: number;
  objectUrl: string;
}

const SUPPORTED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const MASK_UPDATE_DEBOUNCE_MS = 350;

function closeImage(image: DecodedImage | null) {
  if (!image) return;
  if ('naturalWidth' in image) {
    image.removeAttribute('src');
  } else {
    image.close();
  }
}

function decodeWithImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('图片无法解码，请更换一张 JPG、PNG 或 WebP 图片。'));
    image.src = url;
  });
}

async function decodeFile(file: File, objectUrl: string, isCurrent: () => boolean): Promise<DecodedImage> {
  if ('createImageBitmap' in window) {
    try {
      return await createImageBitmap(file);
    } catch {
      // Older WebViews can reject a format even when <img> can display it.
    }
  }
  if (!isCurrent()) throw new Error('图片选择已取消。');
  return decodeWithImage(objectUrl);
}

function getDecodedImageSize(image: DecodedImage): ImageSize {
  if ('naturalWidth' in image) {
    return { width: image.naturalWidth, height: image.naturalHeight };
  }
  return { width: image.width, height: image.height };
}

export function useWordCloudMask(targetSize: ImageSize | null) {
  const [threshold, setThreshold] = useState(128);
  const [inverted, setInverted] = useState(false);
  const [sourcePreviewUrl, setSourcePreviewUrl] = useState<string | null>(null);
  const [sourceSize, setSourceSize] = useState<ImageSize | null>(null);
  const [maskPreviewUrl, setMaskPreviewUrl] = useState<string | null>(null);
  const [appliedMask, setAppliedMask] = useState<HTMLCanvasElement | null>(null);
  const [drawableRatio, setDrawableRatio] = useState<number | null>(null);
  const [decoding, setDecoding] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const loadedRef = useRef<LoadedImage | null>(null);
  const pendingCandidateRef = useRef<PendingCandidate | null>(null);
  const appliedMaskRef = useRef<HTMLCanvasElement | null>(null);
  const appliedSourceVersionRef = useRef(0);
  const candidateIdRef = useRef(0);
  const sourceVersionRef = useRef(0);
  const [revision, setRevision] = useState(0);
  const [appliedVersion, setAppliedVersion] = useState(0);
  const status: ProcessingStatus = decoding ? 'decoding' : processing ? 'processing' : 'idle';

  const releaseLoadedImage = useCallback(() => {
    const loaded = loadedRef.current;
    if (!loaded) return;
    closeImage(loaded.image);
    URL.revokeObjectURL(loaded.objectUrl);
    loadedRef.current = null;
  }, []);

  const releasePendingCandidate = useCallback((candidateId?: number) => {
    const pending = pendingCandidateRef.current;
    if (!pending || (candidateId !== undefined && pending.id !== candidateId)) return;
    URL.revokeObjectURL(pending.objectUrl);
    pendingCandidateRef.current = null;
  }, []);

  const removeMask = useCallback(() => {
    candidateIdRef.current += 1;
    sourceVersionRef.current += 1;
    releasePendingCandidate();
    releaseLoadedImage();
    setSourcePreviewUrl(null);
    setSourceSize(null);
    setMaskPreviewUrl(null);
    setAppliedMask(null);
    appliedMaskRef.current = null;
    appliedSourceVersionRef.current = 0;
    setAppliedVersion(0);
    setDrawableRatio(null);
    setMessage(null);
    setDecoding(false);
    setProcessing(false);
    setRevision(value => value + 1);
  }, [releaseLoadedImage, releasePendingCandidate]);

  const resetMask = useCallback(() => {
    removeMask();
    setThreshold(128);
    setInverted(false);
  }, [removeMask]);

  const selectFile = useCallback(async (file: File) => {
    if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
      setMessage('仅支持 JPG、PNG 或 WebP 图片。');
      return null;
    }
    if (file.size > MAX_MASK_FILE_SIZE) {
      setMessage('图片不能超过 10 MB。');
      return null;
    }

    const candidateId = ++candidateIdRef.current;
    releasePendingCandidate();
    setDecoding(true);
    setMessage(null);
    let image: DecodedImage | null = null;

    try {
      const metadataSize = getImageMetadataSize(new Uint8Array(await file.arrayBuffer()), file.type);
      if (candidateId !== candidateIdRef.current) return null;
      if (!isSourceImageSizeAllowed(metadataSize)) {
        throw new Error('图片单边不能超过 8192 像素。');
      }

      const objectUrl = URL.createObjectURL(file);
      pendingCandidateRef.current = { id: candidateId, objectUrl };
      image = await decodeFile(file, objectUrl, () => candidateId === candidateIdRef.current);
      const decodedSize = getDecodedImageSize(image);
      if (!isSourceImageSizeAllowed(decodedSize)) {
        throw new Error('图片单边不能超过 8192 像素。');
      }
      if (!areImageSizesCompatible(metadataSize, decodedSize)) {
        throw new Error('图片尺寸信息不一致，请更换一张图片。');
      }
      if (candidateId !== candidateIdRef.current) {
        closeImage(image);
        image = null;
        releasePendingCandidate(candidateId);
        return null;
      }

      releaseLoadedImage();
      pendingCandidateRef.current = null;
      loadedRef.current = { image, size: decodedSize, objectUrl };
      image = null;
      const sourceVersion = ++sourceVersionRef.current;
      setSourcePreviewUrl(objectUrl);
      setSourceSize(decodedSize);
      setMaskPreviewUrl(null);
      setAppliedMask(null);
      appliedMaskRef.current = null;
      appliedSourceVersionRef.current = 0;
      setAppliedVersion(0);
      setDrawableRatio(null);
      setDecoding(false);
      setRevision(value => value + 1);
      return sourceVersion;
    } catch (error) {
      closeImage(image);
      releasePendingCandidate(candidateId);
      if (candidateId === candidateIdRef.current) {
        setMessage(error instanceof Error ? error.message : '图片处理失败，请更换一张图片。');
        setDecoding(false);
      }
      return null;
    }
  }, [releaseLoadedImage, releasePendingCandidate]);

  useEffect(() => {
    const loaded = loadedRef.current;
    if (!loaded) return;
    const sourceVersion = sourceVersionRef.current;
    setProcessing(true);

    const timer = window.setTimeout(() => {
      try {
        const processed = createWordCloudMask(loaded.image, loaded.size, threshold, inverted, targetSize ?? undefined);
        if (sourceVersion !== sourceVersionRef.current) return;

        setMaskPreviewUrl(processed.canvas.toDataURL('image/png'));
        setDrawableRatio(processed.drawableRatio);
        const validity = getMaskValidity(processed.drawableRatio);
        if (validity === 'valid') {
          setAppliedMask(processed.canvas);
          appliedMaskRef.current = processed.canvas;
          appliedSourceVersionRef.current = sourceVersion;
          setAppliedVersion(sourceVersion);
          setMessage(null);
        } else if (validity === 'too-small') {
          const hasCurrentMask = appliedMaskRef.current !== null && appliedSourceVersionRef.current === sourceVersion;
          setMessage(hasCurrentMask ? '可生成区域过小，请调整阈值或反转词语区域；已保留上一次有效轮廓。' : '可生成区域过小，请调整阈值或反转词语区域。');
        } else {
          const hasCurrentMask = appliedMaskRef.current !== null && appliedSourceVersionRef.current === sourceVersion;
          setMessage(hasCurrentMask ? '轮廓区分度较低，请调整阈值或反转词语区域；已保留上一次有效轮廓。' : '轮廓区分度较低，请调整阈值或反转词语区域。');
        }
      } catch (error) {
        if (sourceVersion === sourceVersionRef.current) {
          setMessage(error instanceof Error ? error.message : '图片处理失败，请更换一张图片。');
        }
      } finally {
        if (sourceVersion === sourceVersionRef.current) setProcessing(false);
      }
    }, MASK_UPDATE_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [inverted, revision, targetSize, threshold]);

  useEffect(() => () => {
    candidateIdRef.current += 1;
    sourceVersionRef.current += 1;
    releasePendingCandidate();
    releaseLoadedImage();
  }, [releaseLoadedImage, releasePendingCandidate]);

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
